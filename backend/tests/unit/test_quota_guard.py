"""Unit tests for the per-org quota guard (Phase 9, unit C).

Focuses on the pure ``_evaluate`` comparison core (DB-free, py3.9-importable).
``check_org_quota`` is exercised for the flag-off and fail-open paths with a
minimal fake async session.
"""

import asyncio

import pytest

try:
    from app.services.quota_guard import (
        METRIC_DATA_BYTES,
        METRIC_QUERIES,
        METRIC_TOKENS,
        QuotaStatus,
        _evaluate,
        check_org_quota,
        quota_exceeded_error,
    )

    _IMPORT_OK = True
except Exception as _exc:  # pragma: no cover - environment guard
    _IMPORT_OK = False
    _IMPORT_ERR = _exc

pytestmark = pytest.mark.skipif(
    not _IMPORT_OK,
    reason="quota_guard import failed (likely py-version dep): {0}".format(
        _IMPORT_ERR if not _IMPORT_OK else ""
    ),
)


def _policy(tokens=None, queries=None, data_bytes=None):
    return {
        "monthly_token_limit": tokens,
        "monthly_query_limit": queries,
        "monthly_data_bytes_limit": data_bytes,
    }


# ---------------------------------------------------------------------------
# Pure _evaluate cases
# ---------------------------------------------------------------------------

def test_no_policy_allows():
    s = _evaluate(None, {}, metric=METRIC_TOKENS)
    assert s.allowed is True
    assert s.reason == "no_policy"


def test_under_limit_allowed():
    s = _evaluate(_policy(tokens=10000), {METRIC_TOKENS: 9999}, metric=METRIC_TOKENS)
    assert s.allowed is True
    assert s.used == 9999
    assert s.limit == 10000


def test_at_limit_blocked():
    s = _evaluate(_policy(tokens=10000), {METRIC_TOKENS: 10000}, metric=METRIC_TOKENS)
    assert s.allowed is False
    assert s.metric == METRIC_TOKENS
    assert "monthly_token_limit exceeded (10000/10000)" == s.reason


def test_over_limit_blocked():
    s = _evaluate(_policy(tokens=10000), {METRIC_TOKENS: 12000}, metric=METRIC_TOKENS)
    assert s.allowed is False
    assert s.reason == "monthly_token_limit exceeded (12000/10000)"
    assert s.limit == 10000 and s.used == 12000


def test_null_limit_is_unlimited():
    s = _evaluate(_policy(tokens=None), {METRIC_TOKENS: 999999}, metric=METRIC_TOKENS)
    assert s.allowed is True


def test_zero_limit_is_unlimited():
    s = _evaluate(_policy(tokens=0), {METRIC_TOKENS: 999999}, metric=METRIC_TOKENS)
    assert s.allowed is True


def test_metric_none_all_within():
    s = _evaluate(
        _policy(tokens=100, queries=100, data_bytes=100),
        {METRIC_TOKENS: 1, METRIC_QUERIES: 2, METRIC_DATA_BYTES: 3},
        metric=None,
    )
    assert s.allowed is True
    assert s.reason == "within_quota"


def test_metric_none_one_over_names_it():
    s = _evaluate(
        _policy(tokens=100, queries=5, data_bytes=100),
        {METRIC_TOKENS: 1, METRIC_QUERIES: 9, METRIC_DATA_BYTES: 3},
        metric=None,
    )
    assert s.allowed is False
    assert s.metric == METRIC_QUERIES
    assert "monthly_query_limit exceeded (9/5)" == s.reason


def test_metric_none_data_bytes_over():
    s = _evaluate(
        _policy(data_bytes=1000),
        {METRIC_DATA_BYTES: 1000},
        metric=None,
    )
    assert s.allowed is False
    assert s.metric == METRIC_DATA_BYTES


def test_missing_used_treated_as_zero():
    s = _evaluate(_policy(tokens=100), {}, metric=METRIC_TOKENS)
    assert s.allowed is True
    assert s.used == 0


# ---------------------------------------------------------------------------
# check_org_quota async paths (flag-off + fail-open)
# ---------------------------------------------------------------------------

class _FakeSession:
    """Async session whose execute() raises — drives the fail-open path."""

    async def execute(self, *_a, **_k):
        raise RuntimeError("boom")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_check_flag_off_allows(monkeypatch):
    # Force the flag OFF regardless of env.
    import app.settings.hybrid_flags as hf

    monkeypatch.setattr(type(hf.flags), "QUOTAS", property(lambda self: False))
    s = _run(check_org_quota(_FakeSession(), organization_id="org1"))
    assert s.allowed is True
    assert s.reason == "quotas_disabled"


def test_check_fail_open_on_error(monkeypatch):
    import app.settings.hybrid_flags as hf

    monkeypatch.setattr(type(hf.flags), "QUOTAS", property(lambda self: True))
    s = _run(check_org_quota(_FakeSession(), organization_id="org1"))
    assert s.allowed is True
    assert s.reason.startswith("quota_check_error:")


def test_quota_exceeded_error_builds_429():
    status = QuotaStatus(
        allowed=False,
        metric=METRIC_TOKENS,
        limit=10000,
        used=12000,
        reason="monthly_token_limit exceeded (12000/10000)",
    )
    err = quota_exceeded_error(status)
    assert err.status_code == 429
    assert err.error_code == "quota_exceeded"
    assert err.message == "monthly_token_limit exceeded (12000/10000)"
