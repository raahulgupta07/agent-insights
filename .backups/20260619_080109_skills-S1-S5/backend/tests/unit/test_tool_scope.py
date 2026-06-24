"""Unit tests for app.ai.skills.tool_scope (pure, stdlib + pytest only)."""

import importlib.util
import os
import sys

# Insert backend root on sys.path (no conftest in this run).
_BACKEND_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir)
)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

# Load the module directly by file path so the test does not depend on every
# intermediate package having an __init__.py (the module itself is pure).
_MODULE_PATH = os.path.join(
    _BACKEND_ROOT, "app", "ai", "skills", "tool_scope.py"
)
_spec = importlib.util.spec_from_file_location("tool_scope_under_test", _MODULE_PATH)
tool_scope = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool_scope)

narrow_catalog = tool_scope.narrow_catalog
active_skill_tools = tool_scope.active_skill_tools
NEVER_DROP = tool_scope.NEVER_DROP


def _names(catalog):
    return [t["name"] for t in catalog]


def _cat(*names):
    return [{"name": n} for n in names]


# --- empty allowed => no narrowing -----------------------------------------

def test_empty_allowed_no_narrowing():
    catalog = _cat("read", "write", "search")
    out = narrow_catalog(catalog, [])
    assert _names(out) == ["read", "write", "search"]


def test_none_allowed_no_narrowing():
    catalog = _cat("read", "write", "search")
    out = narrow_catalog(catalog, None)
    assert _names(out) == ["read", "write", "search"]


def test_empty_allowed_still_removes_disallowed():
    catalog = _cat("read", "write", "search")
    out = narrow_catalog(catalog, [], disallowed_tools=["write"])
    assert _names(out) == ["read", "search"]


# --- allow-list keeps only those + never_drop ------------------------------

def test_allow_list_keeps_only_allowed_plus_never_drop():
    catalog = _cat("read", "write", "search", "done", "load_skill")
    out = narrow_catalog(catalog, ["read"])
    # read allowed; done + load_skill are never_drop; write/search dropped
    assert _names(out) == ["read", "done", "load_skill"]


def test_allow_list_drops_unallowed():
    catalog = _cat("read", "write", "search")
    out = narrow_catalog(catalog, ["search"])
    assert _names(out) == ["search"]


# --- never_drop survives ----------------------------------------------------

def test_never_drop_survives_when_not_allowed():
    catalog = _cat("read", "clarify")
    out = narrow_catalog(catalog, ["read"])
    assert "clarify" in _names(out)


def test_never_drop_survives_when_disallowed():
    catalog = _cat("read", "done")
    out = narrow_catalog(catalog, [], disallowed_tools=["done", "read"])
    # done is never_drop -> survives; read removed
    assert _names(out) == ["done"]


def test_never_drop_survives_allowed_and_disallowed():
    catalog = _cat("read", "load_skill")
    out = narrow_catalog(catalog, ["read"], disallowed_tools=["load_skill"])
    assert _names(out) == ["read", "load_skill"]


def test_custom_never_drop_set():
    catalog = _cat("read", "write", "done")
    # override never_drop -> default meta tool "done" no longer protected
    out = narrow_catalog(catalog, ["read"], never_drop={"write"})
    assert _names(out) == ["read", "write"]


# --- disallowed removes -----------------------------------------------------

def test_disallowed_removes_even_if_allowed():
    catalog = _cat("read", "write", "search")
    out = narrow_catalog(catalog, ["read", "write"], disallowed_tools=["write"])
    assert _names(out) == ["read"]


# --- order preserved --------------------------------------------------------

def test_order_preserved():
    catalog = _cat("z", "a", "m", "b")
    out = narrow_catalog(catalog, ["b", "z", "a", "m"])
    assert _names(out) == ["z", "a", "m", "b"]


# --- dedupe -----------------------------------------------------------------

def test_dedupe_by_name_first_wins():
    catalog = [
        {"name": "read", "v": 1},
        {"name": "read", "v": 2},
        {"name": "write", "v": 3},
    ]
    out = narrow_catalog(catalog, [])
    assert _names(out) == ["read", "write"]
    assert out[0]["v"] == 1  # first occurrence kept


def test_dedupe_with_never_drop():
    catalog = _cat("done", "done", "read")
    out = narrow_catalog(catalog, ["read"])
    assert _names(out) == ["done", "read"]


# --- items without "name" dropped ------------------------------------------

def test_items_without_name_dropped():
    catalog = [{"name": "read"}, {"desc": "no name"}, {"name": None}, {"name": "write"}]
    out = narrow_catalog(catalog, [])
    assert _names(out) == ["read", "write"]


def test_non_mapping_items_dropped():
    catalog = [{"name": "read"}, "not a dict", 42, None, {"name": "write"}]
    out = narrow_catalog(catalog, [])
    assert _names(out) == ["read", "write"]


# --- None / bad inputs safe -------------------------------------------------

def test_none_catalog_returned_as_is():
    assert narrow_catalog(None, ["read"]) is None


def test_non_list_catalog_returned_as_is():
    obj = {"name": "read"}
    assert narrow_catalog(obj, ["read"]) is obj
    assert narrow_catalog("string", []) == "string"


def test_does_not_mutate_input():
    catalog = _cat("read", "write")
    snapshot = list(catalog)
    out = narrow_catalog(catalog, ["read"])
    assert catalog == snapshot  # input untouched
    assert out is not catalog


def test_empty_catalog():
    assert narrow_catalog([], ["read"]) == []


# --- active_skill_tools -----------------------------------------------------

def test_active_skill_tools_none():
    assert active_skill_tools(None) == ([], [])


def test_active_skill_tools_empty_dict():
    assert active_skill_tools({}) == ([], [])


def test_active_skill_tools_full():
    skill = {
        "name": "researcher",
        "allowed_tools": ["read", "search"],
        "disallowed_tools": ["write"],
    }
    allowed, disallowed = active_skill_tools(skill)
    assert allowed == ["read", "search"]
    assert disallowed == ["write"]


def test_active_skill_tools_missing_keys():
    assert active_skill_tools({"name": "x"}) == ([], [])


def test_active_skill_tools_bad_types():
    skill = {"allowed_tools": "read", "disallowed_tools": 5}
    assert active_skill_tools(skill) == ([], [])


def test_active_skill_tools_returns_new_lists():
    allowed_in = ["read"]
    skill = {"allowed_tools": allowed_in}
    allowed, _ = active_skill_tools(skill)
    assert allowed == ["read"]
    assert allowed is not allowed_in  # defensive copy


# --- integration: narrow using active_skill_tools ---------------------------

def test_narrow_with_active_skill_tools():
    catalog = _cat("read", "write", "search", "done")
    skill = {"allowed_tools": ["read"], "disallowed_tools": ["search"]}
    allowed, disallowed = active_skill_tools(skill)
    out = narrow_catalog(catalog, allowed, disallowed_tools=disallowed)
    assert _names(out) == ["read", "done"]


def test_never_drop_constant():
    assert NEVER_DROP == {"load_skill", "read_skill_file", "clarify", "done"}
