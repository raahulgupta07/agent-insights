"""Unit tests for env-tunable async DB pool config helpers.

These import the real helpers from app.settings.database. That module pulls in
the full app config stack (fastapi_mail, pydantic settings, etc.), which may be
unavailable in a bare local env. If the import fails for any reason we skip the
whole module with a clear reason so CI (full deps) still exercises the logic
while local runs degrade gracefully — no helper logic is duplicated here.
"""
import importlib

import pytest

try:
    _db = importlib.import_module("app.settings.database")
    _pool_int = _db._pool_int
    _pool_bool = _db._pool_bool
except Exception as exc:  # pragma: no cover - env-dependent skip
    pytest.skip(
        f"app.settings.database not importable in this env: {exc!r}",
        allow_module_level=True,
    )


# --- _pool_int -------------------------------------------------------------

def test_pool_int_default_when_unset(monkeypatch):
    monkeypatch.delenv("DB_POOL_SIZE", raising=False)
    assert _pool_int("DB_POOL_SIZE", 20) == 20


def test_pool_int_override_when_set(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "50")
    assert _pool_int("DB_POOL_SIZE", 20) == 50


def test_pool_int_invalid_string_falls_back(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "not-a-number")
    assert _pool_int("DB_POOL_SIZE", 20) == 20


def test_pool_int_empty_string_falls_back(monkeypatch):
    monkeypatch.setenv("DB_POOL_SIZE", "")
    assert _pool_int("DB_POOL_SIZE", 20) == 20


def test_pool_int_zero_falls_back(monkeypatch):
    monkeypatch.setenv("DB_MAX_OVERFLOW", "0")
    assert _pool_int("DB_MAX_OVERFLOW", 20) == 20


def test_pool_int_negative_falls_back_by_default(monkeypatch):
    monkeypatch.setenv("DB_POOL_TIMEOUT", "-5")
    assert _pool_int("DB_POOL_TIMEOUT", 30) == 30


def test_pool_int_recycle_accepts_negative_one(monkeypatch):
    monkeypatch.setenv("DB_POOL_RECYCLE", "-1")
    assert _pool_int("DB_POOL_RECYCLE", 1800, allow_negative=True) == -1


def test_pool_int_recycle_default_when_unset(monkeypatch):
    monkeypatch.delenv("DB_POOL_RECYCLE", raising=False)
    assert _pool_int("DB_POOL_RECYCLE", 1800, allow_negative=True) == 1800


def test_pool_int_recycle_invalid_falls_back_even_with_allow_negative(monkeypatch):
    monkeypatch.setenv("DB_POOL_RECYCLE", "garbage")
    assert _pool_int("DB_POOL_RECYCLE", 1800, allow_negative=True) == 1800


# --- _pool_bool ------------------------------------------------------------

def test_pool_bool_default_when_unset(monkeypatch):
    monkeypatch.delenv("DB_POOL_PRE_PING", raising=False)
    assert _pool_bool("DB_POOL_PRE_PING", True) is True


@pytest.mark.parametrize("val", ["1", "true", "TRUE", "Yes", "on", " on "])
def test_pool_bool_truthy(monkeypatch, val):
    monkeypatch.setenv("DB_POOL_PRE_PING", val)
    assert _pool_bool("DB_POOL_PRE_PING", False) is True


@pytest.mark.parametrize("val", ["0", "false", "no", "off", "", "nope"])
def test_pool_bool_falsy(monkeypatch, val):
    monkeypatch.setenv("DB_POOL_PRE_PING", val)
    assert _pool_bool("DB_POOL_PRE_PING", True) is False
