"""Pure unit tests for compute_funnel_stats (no DB, no FastAPI)."""

from app.routes.funnel import compute_funnel_stats


def test_empty_list():
    stats = compute_funnel_stats([])
    assert stats["total"] == 0
    assert stats["cache_hit"] == 0
    assert stats["cache_hit_rate"] == 0.0
    assert stats["p50_ms"] is None
    assert stats["p95_ms"] is None
    assert stats["p50_cache_ms"] is None
    assert stats["p50_cold_ms"] is None
    assert stats["by_tier"] == {
        "reasoning_cache": 0,
        "answer_cache": 0,
        "materialized": 0,
        "agent_loop": 0,
    }


def test_mixed_rows():
    rows = [
        {"served_by": "reasoning_cache", "elapsed_ms": 100, "status": "success"},
        {"served_by": "reasoning_cache", "elapsed_ms": 200, "status": "success"},
        {"served_by": "answer_cache", "elapsed_ms": 300, "status": "success"},
        {"served_by": "agent_loop", "elapsed_ms": 4000, "status": "success"},
        {"served_by": None, "elapsed_ms": 6000, "status": "success"},  # -> agent_loop
        {"served_by": "reasoning_cache", "elapsed_ms": 999, "status": "error"},  # ignored
    ]
    stats = compute_funnel_stats(rows)

    # 5 success rows (the error row is ignored)
    assert stats["total"] == 5
    assert stats["by_tier"] == {
        "reasoning_cache": 2,
        "answer_cache": 1,
        "materialized": 0,
        "agent_loop": 2,  # explicit agent_loop + NULL served_by
    }

    # cache hits = everything that is not agent_loop = 3
    assert stats["cache_hit"] == 3
    assert stats["cache_hit_rate"] == round(3 / 5, 4)  # 0.6

    # percentiles over all success elapsed_ms: [100,200,300,4000,6000]
    assert isinstance(stats["p50_ms"], int)
    assert stats["p50_ms"] == 300  # median of 5 values
    assert isinstance(stats["p95_ms"], int)
    assert stats["p95_ms"] >= stats["p50_ms"]

    # cache subset elapsed = [100,200,300] -> p50 200
    assert stats["p50_cache_ms"] == 200
    # cold (agent_loop) subset elapsed = [4000,6000] -> p50 = 5000 (interp)
    assert stats["p50_cold_ms"] == 5000


def test_no_elapsed_values():
    rows = [
        {"served_by": "answer_cache", "elapsed_ms": None, "status": "success"},
        {"served_by": "agent_loop", "elapsed_ms": None, "status": "success"},
        {"served_by": "answer_cache", "status": "success"},  # missing elapsed key
    ]
    stats = compute_funnel_stats(rows)

    assert stats["total"] == 3
    assert stats["by_tier"]["answer_cache"] == 2
    assert stats["by_tier"]["agent_loop"] == 1
    assert stats["cache_hit"] == 2
    assert stats["cache_hit_rate"] == round(2 / 3, 4)

    # no usable elapsed data -> all percentiles None
    assert stats["p50_ms"] is None
    assert stats["p95_ms"] is None
    assert stats["p50_cache_ms"] is None
    assert stats["p50_cold_ms"] is None


def test_non_int_elapsed_skipped():
    rows = [
        {"served_by": "materialized", "elapsed_ms": "not-a-number", "status": "success"},
        {"served_by": "materialized", "elapsed_ms": 500, "status": "success"},
    ]
    stats = compute_funnel_stats(rows)
    assert stats["total"] == 2
    assert stats["by_tier"]["materialized"] == 2
    assert stats["cache_hit"] == 2
    # only the 500 value is usable
    assert stats["p50_ms"] == 500
