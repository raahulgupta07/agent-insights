"""Pack registry — load + validate + cache the declarative pack library.

Packs live as ``*.yaml`` files under ``packs/library/`` (next to this module).
Each file is a self-contained domain method. The registry reads them once,
validates a minimal schema, and serves them in-memory. Pure data, no exec.

Pack schema (minimal — extra keys are preserved verbatim):
  id:             str   unique slug, e.g. "ebitda-good-bad-ugly"
  name:           str   human label shown in the Skills UI
  domain:         str   dotted domain, e.g. "finance.exec-summary"
  trigger_hints:  list[str]   phrases that hint the pack is relevant
  required_inputs: dict[str, {role?, dtype?, synonyms?[], desc?}]
                  logical inputs the method needs; the binder maps each to a
                  real column. An input may also carry "optional": true.
  method_text:    str   the INVARIANT method (copied into planner context)
  output_spec:    dict  shape of the deliverable (type/sections/format/...)
  eval_goldens:   list  expected results, snapshotted at bind time (may be [])
  format:         dict  optional output formatting rules

Never raises: a malformed pack file is skipped (logged) and the rest load.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Dict, List, Optional

_LIBRARY_DIR = os.path.join(os.path.dirname(__file__), "library")

_REQUIRED_KEYS = ("id", "name", "method_text")

# module-level cache: {pack_id: pack_dict}. Guarded by _LOCK. Lazily filled.
_CACHE: Optional[Dict[str, dict]] = None
_LOCK = threading.Lock()


def _validate(pack: Any, src: str) -> Optional[dict]:
    """Return the pack dict if it has the required keys, else None."""
    if not isinstance(pack, dict):
        return None
    for k in _REQUIRED_KEYS:
        if not pack.get(k):
            return None
    # normalise the loose-typed fields so downstream code is simple
    pack.setdefault("domain", "general")
    pack.setdefault("trigger_hints", [])
    pack.setdefault("required_inputs", {})
    pack.setdefault("output_spec", {})
    pack.setdefault("eval_goldens", [])
    pack.setdefault("format", {})
    pack["_source"] = os.path.basename(src)
    if not isinstance(pack.get("required_inputs"), dict):
        pack["required_inputs"] = {}
    if not isinstance(pack.get("trigger_hints"), list):
        pack["trigger_hints"] = []
    return pack


def _load_from_disk() -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    try:
        import yaml  # pyyaml is in the image
    except Exception:
        return out
    try:
        names = os.listdir(_LIBRARY_DIR)
    except Exception:
        return out
    for fn in sorted(names):
        if not (fn.endswith(".yaml") or fn.endswith(".yml")):
            continue
        path = os.path.join(_LIBRARY_DIR, fn)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                doc = yaml.safe_load(fh)
        except Exception:
            continue  # skip a broken file, keep the rest
        pack = _validate(doc, path)
        if pack is None:
            continue
        pid = str(pack["id"]).strip()
        if pid:
            out[pid] = pack
    return out


def all_packs(force_reload: bool = False) -> Dict[str, dict]:
    """Return {pack_id: pack} for the whole library (cached)."""
    global _CACHE
    if _CACHE is not None and not force_reload:
        return _CACHE
    with _LOCK:
        if _CACHE is None or force_reload:
            _CACHE = _load_from_disk()
    return _CACHE


def get_pack(pack_id: str) -> Optional[dict]:
    """Return one pack by id, or None."""
    if not pack_id:
        return None
    return all_packs().get(str(pack_id).strip())


def list_packs() -> List[dict]:
    """All packs as a list (for the Skills UI / debugging)."""
    return list(all_packs().values())
