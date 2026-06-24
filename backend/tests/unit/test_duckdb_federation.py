"""Unit tests for the DuckDB federation engine + freshness policy (Phase 7).

Deterministic, no Postgres, no LLM, no app conftest fixtures. Importable under
``--noconftest`` and on Python 3.9 (no ``X | None`` syntax — Optional only).

The engine + freshness modules are loaded directly from their file paths
(importlib-by-path), the same pattern as ``test_llm_concurrency.py``, so we do
not execute heavy package ``__init__`` side effects. The freshness module is
stdlib-only; the engine module lazy-imports duckdb so it loads fine even when
duckdb is absent.

Contract under test:
    freshness.resolve_policy — pure mode selection + defaults (no skip).
    duckdb_engine.run_federated_sql:
        * FEDERATION flag off  -> returns None WITHOUT importing duckdb.
        * (duckdb present) flag on -> federates a registered DataFrame.
        * bounding knobs (memory_limit / threads) SET without error.
"""

from __future__ import annotations

import importlib.util
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_CE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(_HERE)), "app", "ai", "code_execution"
)


def _load(mod_name, filename):
    path = os.path.join(_CE_DIR, filename)
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    # Register before exec: dataclasses resolves field types via the module's
    # entry in sys.modules (cls.__module__), so a path-loaded @dataclass module
    # must be present there or @dataclass raises AttributeError on a NoneType.
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


freshness = _load("_freshness_under_test", "freshness.py")
# duckdb_engine imports `from app.settings.hybrid_flags import flags`, so the
# repo root must be importable. tests/unit is under backend/, and pytest is run
# from backend/, so `app` is on sys.path already; loading by path is still safe
# because the only package import is the stdlib-clean hybrid_flags module.
engine = _load("_duckdb_engine_under_test", "duckdb_engine.py")

_HAS_DUCKDB = importlib.util.find_spec("duckdb") is not None


# --- freshness.resolve_policy (pure, always runs) --------------------------


def test_freshness_default_is_live():
    p = freshness.resolve_policy({})
    assert p.mode == freshness.LIVE
    assert p.ttl_seconds is None
    assert p.is_live


def test_freshness_none_meta_is_live():
    p = freshness.resolve_policy(None)
    assert p.mode == freshness.LIVE


def test_freshness_heavy_is_materialized():
    p = freshness.resolve_policy({"heavy": True})
    assert p.mode == freshness.MATERIALIZED
    assert p.ttl_seconds is None


def test_freshness_correlated_is_materialized():
    p = freshness.resolve_policy({"correlated": True, "needs_fresh": True})
    # heavy/correlated wins over needs_fresh.
    assert p.mode == freshness.MATERIALIZED


def test_freshness_small_fresh_is_live():
    p = freshness.resolve_policy({"small": True, "needs_fresh": True})
    assert p.mode == freshness.LIVE


def test_freshness_repeat_tolerant_is_cached_with_ttl():
    p = freshness.resolve_policy({"repeat": True, "tolerant": True})
    assert p.mode == freshness.CACHED
    assert p.ttl_seconds == freshness.DEFAULT_CACHE_TTL_SECONDS


def test_freshness_explicit_cached_honours_ttl():
    p = freshness.resolve_policy({"mode": "cached", "ttl_seconds": 42})
    assert p.mode == freshness.CACHED
    assert p.ttl_seconds == 42


def test_freshness_explicit_override_wins():
    p = freshness.resolve_policy({"mode": "materialized", "needs_fresh": True})
    assert p.mode == freshness.MATERIALIZED


def test_freshness_invalid_mode_falls_back_to_live():
    # Direct construction of an unknown mode is sanitised to LIVE.
    p = freshness.FreshnessPolicy("nonsense", ttl_seconds=10)
    assert p.mode == freshness.LIVE
    assert p.ttl_seconds is None


def test_freshness_ttl_dropped_for_non_cached():
    p = freshness.FreshnessPolicy(freshness.LIVE, ttl_seconds=99)
    assert p.ttl_seconds is None


def test_freshness_bad_ttl_coerces_to_default():
    p = freshness.resolve_policy({"mode": "cached", "ttl_seconds": "oops"})
    assert p.ttl_seconds == freshness.DEFAULT_CACHE_TTL_SECONDS


# --- engine config knobs (pure, always run) --------------------------------


def test_memory_limit_default_and_override(monkeypatch):
    monkeypatch.delenv("DUCKDB_MEMORY_LIMIT", raising=False)
    assert engine._memory_limit() == "512MB"
    monkeypatch.setenv("DUCKDB_MEMORY_LIMIT", "1GB")
    assert engine._memory_limit() == "1GB"


def test_threads_parsing(monkeypatch):
    monkeypatch.delenv("DUCKDB_THREADS", raising=False)
    assert engine._threads() is None
    monkeypatch.setenv("DUCKDB_THREADS", "4")
    assert engine._threads() == 4
    monkeypatch.setenv("DUCKDB_THREADS", "0")
    assert engine._threads() is None
    monkeypatch.setenv("DUCKDB_THREADS", "abc")
    assert engine._threads() is None


def test_temp_dir(monkeypatch):
    monkeypatch.delenv("DUCKDB_TEMP_DIR", raising=False)
    assert engine._temp_dir() is None
    monkeypatch.setenv("DUCKDB_TEMP_DIR", "/tmp/duck")
    assert engine._temp_dir() == "/tmp/duck"


# --- flag gating (no duckdb import needed) ---------------------------------


def test_flag_off_returns_none_without_duckdb(monkeypatch):
    # FEDERATION off => no-op, must not require duckdb at all.
    monkeypatch.delenv("HYBRID_FEDERATION", raising=False)
    assert engine.flags.FEDERATION is False
    assert engine.run_federated_sql("SELECT 1") is None


def test_flag_on_empty_sql_returns_none(monkeypatch):
    monkeypatch.setenv("HYBRID_FEDERATION", "1")
    assert engine.flags.FEDERATION is True
    assert engine.run_federated_sql("") is None
    assert engine.run_federated_sql("   ") is None


def test_safe_identifier_rejects_injection():
    with pytest.raises(ValueError):
        engine._safe_identifier("drop; --")
    with pytest.raises(ValueError):
        engine._safe_identifier("a b")
    assert engine._safe_identifier("good_name1") == "good_name1"


def test_snapshot_stub_raises():
    with pytest.raises(NotImplementedError):
        engine.snapshot_to_parquet("anything")


# --- live duckdb federation (skip if dep absent) ---------------------------


@pytest.mark.skipif(not _HAS_DUCKDB, reason="duckdb not installed")
def test_register_dataframe_and_count(monkeypatch):
    import pandas as pd

    monkeypatch.setenv("HYBRID_FEDERATION", "1")
    df = pd.DataFrame({"x": [1, 2, 3, 4], "g": ["a", "a", "b", "b"]})

    out = engine.run_federated_sql(
        "SELECT count(*) AS n FROM t", dataframes={"t": df}
    )
    assert out is not None
    assert int(out.iloc[0]["n"]) == 4


@pytest.mark.skipif(not _HAS_DUCKDB, reason="duckdb not installed")
def test_federated_groupby(monkeypatch):
    import pandas as pd

    monkeypatch.setenv("HYBRID_FEDERATION", "1")
    df = pd.DataFrame({"x": [1, 2, 3, 4], "g": ["a", "a", "b", "b"]})

    out = engine.run_federated_sql(
        "SELECT g, sum(x) AS s FROM t GROUP BY g ORDER BY g", dataframes={"t": df}
    )
    assert out is not None
    by_g = dict(zip(out["g"], out["s"]))
    assert by_g["a"] == 3
    assert by_g["b"] == 7


@pytest.mark.skipif(not _HAS_DUCKDB, reason="duckdb not installed")
def test_bounding_knobs_applied(monkeypatch):
    # memory_limit + threads SET must not error and the connection must work.
    monkeypatch.setenv("HYBRID_FEDERATION", "1")
    monkeypatch.setenv("DUCKDB_MEMORY_LIMIT", "256MB")
    monkeypatch.setenv("DUCKDB_THREADS", "2")
    with engine.duckdb_connection() as con:
        val = con.execute("SELECT 21 + 21 AS v").df()
        assert int(val.iloc[0]["v"]) == 42
        # Confirm the memory_limit setting took effect.
        ml = con.execute("SELECT current_setting('memory_limit') AS m").df()
        assert ml.iloc[0]["m"]  # non-empty string like '256.0 MiB'


@pytest.mark.skipif(not _HAS_DUCKDB, reason="duckdb not installed")
def test_read_parquet_roundtrip(monkeypatch, tmp_path):
    import pandas as pd

    monkeypatch.setenv("HYBRID_FEDERATION", "1")
    pq = tmp_path / "data.parquet"
    pd.DataFrame({"v": [10, 20, 30]}).to_parquet(pq)

    out = engine.run_federated_sql(
        "SELECT sum(v) AS s FROM p", parquet={"p": str(pq)}
    )
    assert out is not None
    assert int(out.iloc[0]["s"]) == 60
