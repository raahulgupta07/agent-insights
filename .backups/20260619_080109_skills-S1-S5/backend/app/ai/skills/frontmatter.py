"""Claude-Code-style SKILL.md YAML frontmatter parsing/serialization.

Pure module: no DB, no I/O, never raises. A SKILL.md is a markdown body that
may carry a leading YAML frontmatter block delimited by '---' lines::

    ---
    name: foo
    description: bar
    allowed-tools: Read Bash create_data
    ---
    <body markdown>

This module splits/normalizes that frontmatter and can serialize it back.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import yaml

__all__ = ["parse_frontmatter", "build_skill_md", "extract_skill_fields"]

_TRUTHY = {"true", "yes", "1", "on"}


def parse_frontmatter(skill_md: str) -> Tuple[Dict[str, Any], str]:
    """Split a SKILL.md into ``(frontmatter_dict, body)``.

    Frontmatter is a leading YAML block delimited by ``---`` lines. If there is
    no leading frontmatter block, returns ``({}, skill_md)`` unchanged.
    Tolerant: malformed YAML / non-dict yaml -> ``({}, original)``. Never raises.
    """
    try:
        if not isinstance(skill_md, str):
            return {}, skill_md

        # Normalize line endings for delimiter detection without mutating body
        # content semantics (we slice off the original string instead).
        stripped = skill_md.lstrip("﻿")  # tolerate a leading BOM
        # Leading whitespace-only lines before the opening '---' are not allowed
        # by the convention; the block must be at the very top.
        lines = stripped.splitlines(keepends=True)
        if not lines:
            return {}, skill_md

        first = lines[0].rstrip("\r\n")
        if first.strip() != "---":
            return {}, skill_md

        # Find the closing '---' delimiter.
        close_idx = None
        for i in range(1, len(lines)):
            if lines[i].rstrip("\r\n").strip() == "---":
                close_idx = i
                break

        if close_idx is None:
            # No closing delimiter -> not a valid frontmatter block.
            return {}, skill_md

        fm_text = "".join(lines[1:close_idx])
        body = "".join(lines[close_idx + 1:])
        # Strip a single leading blank line between the block and the body.
        if body.startswith("\r\n"):
            body = body[2:]
        elif body.startswith("\n"):
            body = body[1:]

        loaded = yaml.safe_load(fm_text)
        if not isinstance(loaded, dict):
            return {}, skill_md

        return loaded, body
    except Exception:
        return {}, skill_md


def build_skill_md(frontmatter: Dict[str, Any], body: str) -> str:
    """Serialize ``frontmatter`` + ``body`` back into a SKILL.md string.

    Produces a leading ``---`` YAML ``---`` block, a blank line, then the body.
    Empty/falsy frontmatter -> return ``body`` unchanged (no empty block).
    Never raises.
    """
    try:
        body = body if isinstance(body, str) else ("" if body is None else str(body))
        if not frontmatter:
            return body
        dumped = yaml.safe_dump(
            frontmatter,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=True,
        )
        return "---\n" + dumped + "---\n\n" + body
    except Exception:
        # On serialization failure, fall back to returning the body verbatim.
        return body if isinstance(body, str) else ""


def _as_tool_list(value: Any) -> List[str]:
    """Coerce a YAML list OR a space-separated string into a list[str]."""
    if value is None:
        return []
    if isinstance(value, str):
        return value.split()
    if isinstance(value, (list, tuple)):
        out: List[str] = []
        for item in value:
            if item is None:
                continue
            out.extend(str(item).split())
        return out
    # Anything else (e.g. a single non-string scalar) -> stringify + split.
    return str(value).split()


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in _TRUTHY
    return bool(value)


def _pick(fm: Dict[str, Any], underscore: str, hyphen: str) -> Any:
    """Return the value for a field accepting both hyphen and underscore keys.

    Underscore form wins if both are present.
    """
    if underscore in fm:
        return fm[underscore]
    if hyphen in fm:
        return fm[hyphen]
    return None


def extract_skill_fields(skill_md: str) -> Dict[str, Any]:
    """Parse frontmatter and return a normalized dict of persisted fields.

    See module docstring / task spec for the exact shape and rules. Never
    raises; on any error returns safe all-default dict with ``body=skill_md``.
    """
    defaults: Dict[str, Any] = {
        "name": None,
        "description": None,
        "allowed_tools": [],
        "disallowed_tools": [],
        "disable_model_invocation": False,
        "user_invocable": True,
        "metadata": {},
        "license": None,
        "body": skill_md if isinstance(skill_md, str) else "",
    }

    try:
        fm, body = parse_frontmatter(skill_md)
        if not isinstance(fm, dict):
            return defaults

        name = fm.get("name")
        description = fm.get("description")
        metadata = fm.get("metadata")
        license_ = fm.get("license")

        return {
            "name": str(name) if name is not None else None,
            "description": str(description) if description is not None else None,
            "allowed_tools": _as_tool_list(
                _pick(fm, "allowed_tools", "allowed-tools")
            ),
            "disallowed_tools": _as_tool_list(
                _pick(fm, "disallowed_tools", "disallowed-tools")
            ),
            "disable_model_invocation": _as_bool(
                _pick(fm, "disable_model_invocation", "disable-model-invocation"),
                False,
            ),
            "user_invocable": _as_bool(
                _pick(fm, "user_invocable", "user-invocable"),
                True,
            ),
            "metadata": metadata if isinstance(metadata, dict) else {},
            "license": str(license_) if license_ is not None else None,
            "body": body if isinstance(body, str) else "",
        }
    except Exception:
        return defaults
