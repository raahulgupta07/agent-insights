"""Pure unit tests for the param-swap (Mode-2) literal-swap helper.

Deterministic, no Postgres, no LLM, no app conftest fixtures. Runnable under
``--noconftest`` and on Python 3.9 (Optional, no ``X | None`` syntax).

We load ``query_cache_serve`` by FILE PATH (same pattern as
``test_llm_concurrency.py``) so we don't import the heavy ``app`` package. The
serve module imports ``app.settings.hybrid_flags`` and
``app.ai.brain.query_cache_store`` at module top, so before loading it we
pre-register lightweight, real (path-loaded, stdlib-only) stand-ins for those
modules under their package names in ``sys.modules``. Both target modules are
themselves stdlib-only at import time (sqlalchemy is function-local), so this
keeps the load self-contained without pulling in provider clients / DB deps.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import types

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(os.path.dirname(_HERE))


def _load_by_path(mod_name, rel_path):
    path = os.path.join(_BACKEND, *rel_path)
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _bootstrap_serve_module():
    # Register namespace packages so the absolute imports inside the target
    # modules resolve to our path-loaded stand-ins, not the real heavy package.
    for pkg in ("app", "app.settings", "app.ai", "app.ai.brain"):
        if pkg not in sys.modules:
            m = types.ModuleType(pkg)
            m.__path__ = []  # mark as a package
            sys.modules[pkg] = m

    _load_by_path("app.settings.hybrid_flags", ("app", "settings", "hybrid_flags.py"))
    _load_by_path("app.ai.brain.query_cache_store", ("app", "ai", "brain", "query_cache_store.py"))
    return _load_by_path(
        "app.ai.brain.query_cache_serve", ("app", "ai", "brain", "query_cache_serve.py")
    )


serve = _bootstrap_serve_module()
swap_literals = serve.swap_literals


# --- single-literal swaps ---------------------------------------------------

def test_single_number_swap():
    out = swap_literals(
        "top products for 30 outlets",
        "SELECT * FROM sales LIMIT 30",
        "top products for 50 outlets",
    )
    assert out == "SELECT * FROM sales LIMIT 50"


def test_single_quoted_string_swap():
    out = swap_literals(
        "sales in North region",
        "SELECT * FROM sales WHERE region = 'North'",
        "sales in South region",
    )
    assert out == "SELECT * FROM sales WHERE region = 'South'"


def test_number_swap_respects_word_boundary():
    # The literal 30 must not match inside 300; only the standalone LIMIT 30.
    out = swap_literals(
        "rows for 30 days",
        "SELECT * FROM t WHERE budget = 300 LIMIT 30",
        "rows for 50 days",
    )
    assert out == "SELECT * FROM t WHERE budget = 300 LIMIT 50"


def test_two_literal_swaps_clean_mapping():
    out = swap_literals(
        "sales in North over 30 days",
        "SELECT * FROM sales WHERE region = 'North' AND days = 30",
        "sales in South over 60 days",
    )
    assert out == "SELECT * FROM sales WHERE region = 'South' AND days = 60"


# --- bail conditions --------------------------------------------------------

def test_bail_on_structural_difference():
    # Extra word -> token-length mismatch -> structural diff -> None.
    assert (
        swap_literals(
            "top products for 30 outlets",
            "SELECT * FROM sales LIMIT 30",
            "top selling products for 30 outlets",
        )
        is None
    )


def test_bail_on_different_word_not_literal():
    # Same length, but the differing token swaps a real word ('top' vs 'best');
    # 'top' is a bare token, but it does not occur verbatim in the SQL -> None.
    assert (
        swap_literals(
            "top products for 30 outlets",
            "SELECT * FROM sales LIMIT 30",
            "best products for 30 outlets",
        )
        is None
    )


def test_bail_on_literal_count_mismatch():
    # Two positions differ in the questions, but one of them ('outlets' ->
    # 'stores') is not present in the SQL -> clean 1:1 mapping fails -> None.
    assert (
        swap_literals(
            "30 outlets",
            "SELECT * FROM sales LIMIT 30",
            "50 stores",
        )
        is None
    )


def test_bail_when_old_literal_absent_from_sql():
    assert (
        swap_literals(
            "sales in North region",
            "SELECT * FROM sales WHERE region = 'West'",
            "sales in South region",
        )
        is None
    )


def test_bail_when_old_literal_appears_twice():
    # 'North' occurs twice in the SQL -> ambiguous -> None.
    assert (
        swap_literals(
            "sales in North region",
            "SELECT * FROM sales WHERE region = 'North' OR origin = 'North'",
            "sales in South region",
        )
        is None
    )


def test_bail_when_swapped_sql_not_read_only():
    # Not a SELECT/WITH to begin with -> swapped result is not read-only -> None.
    assert (
        swap_literals(
            "delete 30 rows",
            "DELETE FROM sales LIMIT 30",
            "delete 50 rows",
        )
        is None
    )


def test_bail_on_exact_match_no_diff():
    # Identical questions -> zero differing tokens -> not our job -> None.
    assert (
        swap_literals(
            "top products for 30 outlets",
            "SELECT * FROM sales LIMIT 30",
            "top products for 30 outlets",
        )
        is None
    )


def test_bail_on_empty_inputs():
    assert swap_literals("", "SELECT 1", "anything") is None
    assert swap_literals("a question", "", "a question changed") is None
    assert swap_literals("a question", "SELECT 1", "") is None
