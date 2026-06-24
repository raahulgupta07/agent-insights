"""
Unit tests for app/ai/skills/files.py — focus on safe_rel_path (PURE).

safe_rel_path is the L3 resource path guard: no DB, never raises. The async DB
fns (add/list/get_skill_file) need the full model registry, so they are NOT
unit-tested here — they run in CI integration tests.

The module is loaded via importlib (not a plain import) because `app/ai/` has
no __init__.py, so `import app.ai.skills.files` is not importable as a package.
Backend root is inserted on sys.path so the module's own `from app...` lazy
imports resolve if ever touched.
"""

import importlib.util
import os
import sys

import pytest

_BACKEND_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

_FILES_PY = os.path.join(_BACKEND_ROOT, "app", "ai", "skills", "files.py")
_spec = importlib.util.spec_from_file_location("skill_files_mod", _FILES_PY)
files = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(files)

safe_rel_path = files.safe_rel_path


# ----- valid paths -----

def test_bare_file_ok():
    assert safe_rel_path("file.md") == "file.md"


def test_one_level_dir_ok():
    assert safe_rel_path("scripts/q.sql") == "scripts/q.sql"


def test_backslash_normalized():
    assert safe_rel_path("scripts\\q.sql") == "scripts/q.sql"


def test_backslash_bare_normalized():
    assert safe_rel_path("file.md") == "file.md"


def test_whitespace_trimmed():
    assert safe_rel_path("  scripts/q.sql  ") == "scripts/q.sql"


# ----- rejected paths -----

def test_none_rejected():
    assert safe_rel_path(None) is None


def test_empty_rejected():
    assert safe_rel_path("") is None


def test_whitespace_only_rejected():
    assert safe_rel_path("   ") is None


def test_absolute_posix_rejected():
    assert safe_rel_path("/etc/passwd") is None


def test_absolute_windows_drive_rejected():
    assert safe_rel_path("C:/Windows/system32") is None


def test_parent_traversal_rejected():
    assert safe_rel_path("../secrets.txt") is None


def test_parent_traversal_mid_rejected():
    assert safe_rel_path("scripts/../q.sql") is None


def test_backslash_traversal_rejected():
    assert safe_rel_path("..\\secrets.txt") is None


def test_deep_three_segments_rejected():
    assert safe_rel_path("a/b/c.sql") is None


def test_deep_four_segments_rejected():
    assert safe_rel_path("a/b/c/d.sql") is None


def test_current_dir_segment_rejected():
    assert safe_rel_path("./file.md") is None


def test_empty_segment_rejected():
    assert safe_rel_path("scripts//q.sql") is None


def test_trailing_slash_rejected():
    # 'scripts/' -> segments ['scripts',''] -> empty segment -> None
    assert safe_rel_path("scripts/") is None


def test_non_string_rejected():
    assert safe_rel_path(123) is None


# ----- kind constants sanity -----

def test_valid_kinds():
    assert files.VALID_KINDS == {"script", "reference", "asset"}
