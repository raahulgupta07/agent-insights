"""Unit tests for the build_data_asset tool (Phase 3, Engineer capability).

Deterministic, no Postgres, no LLM — the DDL execution is patched and a fake
async DB captures the recorded Instruction. The full agent-loop integration
(build → Analyst reuses) is covered by an e2e test (3.5b) that needs a live DB.

Covers:
 - flag gate (HYBRID_ENGINEER_ASSETS off → refuses, no DDL)
 - input validation (bad name, non-SELECT body, multi-statement)
 - correct DDL wrapping per kind (view / materialized_view / table)
 - Instruction recorded as AI-sourced data_asset on success
 - DB-level guard violation surfaces as a failed observation
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.ai.tools.implementations import build_data_asset as mod
from app.ai.tools.implementations.build_data_asset import BuildDataAssetTool


class _FakeDB:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass


def _run(tool_input, runtime_ctx):
    """Drive the async generator to completion, return the list of events."""
    async def _collect():
        return [e async for e in BuildDataAssetTool().run_stream(tool_input, runtime_ctx)]

    return asyncio.run(_collect())


def _final_output(events):
    end = [e for e in events if e.type == "tool.end"][-1]
    return end.payload["output"]


def _ctx():
    return {"db": _FakeDB(), "organization": SimpleNamespace(id="org1")}


def test_flag_off_refuses(monkeypatch):
    monkeypatch.setenv("HYBRID_ENGINEER_ASSETS", "0")
    captured = []
    monkeypatch.setattr(mod, "_execute_ddl", lambda ddl: captured.append(ddl))
    out = _final_output(_run({"name": "x", "kind": "view", "select_sql": "SELECT 1", "description": "d"}, _ctx()))
    assert out["success"] is False
    assert "disabled" in out["error_message"].lower()
    assert captured == []  # no DDL executed when flag off


def test_creates_view_and_records_instruction(monkeypatch):
    monkeypatch.setenv("HYBRID_ENGINEER_ASSETS", "1")
    captured = []
    monkeypatch.setattr(mod, "_execute_ddl", lambda ddl: captured.append(ddl))
    ctx = _ctx()
    out = _final_output(_run(
        {"name": "monthly_mrr", "kind": "view",
         "select_sql": "SELECT date_trunc('month', started_at) m, sum(mrr) FROM public.subscriptions GROUP BY 1",
         "description": "Monthly MRR. cols: m (date), sum (numeric)."},
        ctx,
    ))
    assert out["success"] is True
    assert out["object"] == "analytics.monthly_mrr"
    assert len(captured) == 1
    assert captured[0].startswith("CREATE OR REPLACE VIEW analytics.monthly_mrr AS")
    assert "public.subscriptions" in captured[0]  # reading company data is allowed
    # Instruction recorded, AI-sourced, discoverable
    assert len(ctx["db"].added) == 1
    inst = ctx["db"].added[0]
    assert inst.source_type == "ai"
    assert inst.category == "data_asset"
    assert "analytics.monthly_mrr" in inst.text
    assert inst.structured_data["object"] == "analytics.monthly_mrr"


def test_materialized_and_table_ddl(monkeypatch):
    monkeypatch.setenv("HYBRID_ENGINEER_ASSETS", "1")
    captured = []
    monkeypatch.setattr(mod, "_execute_ddl", lambda ddl: captured.append(ddl))
    _run({"name": "m", "kind": "materialized_view", "select_sql": "SELECT 1", "description": "d"}, _ctx())
    _run({"name": "t", "kind": "table", "select_sql": "SELECT 1", "description": "d"}, _ctx())
    assert captured[0].startswith("CREATE MATERIALIZED VIEW IF NOT EXISTS analytics.m AS")
    assert captured[1].startswith("CREATE TABLE IF NOT EXISTS analytics.t AS")


@pytest.mark.parametrize("bad", [
    {"name": "Bad-Name", "kind": "view", "select_sql": "SELECT 1", "description": "d"},
    {"name": "x", "kind": "view", "select_sql": "DROP TABLE y", "description": "d"},
    {"name": "x", "kind": "view", "select_sql": "SELECT 1; DROP TABLE y", "description": "d"},
])
def test_invalid_input_rejected(monkeypatch, bad):
    monkeypatch.setenv("HYBRID_ENGINEER_ASSETS", "1")
    captured = []
    monkeypatch.setattr(mod, "_execute_ddl", lambda ddl: captured.append(ddl))
    out = _final_output(_run(bad, _ctx()))
    assert out["success"] is False
    assert captured == []  # rejected before any DDL


def test_guard_violation_surfaces(monkeypatch):
    monkeypatch.setenv("HYBRID_ENGINEER_ASSETS", "1")

    def _boom(ddl):
        raise RuntimeError("analytics_write_violation: blocked")

    monkeypatch.setattr(mod, "_execute_ddl", _boom)
    out = _final_output(_run({"name": "x", "kind": "view", "select_sql": "SELECT 1", "description": "d"}, _ctx()))
    assert out["success"] is False
    assert "violation" in out["error_message"].lower()
