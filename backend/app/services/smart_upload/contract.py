"""Smart Upload — the stable route-record contract.

The classifier (``classifier.py``) decides, for each uploaded file, **where it
should go**. This module is the single import point for the API layer (built
later) so the destination constants and the record shape live in ONE place and
never drift between the brain and the route.

Dependency-light on purpose: stdlib ``typing`` only (no pydantic, no DB). The
runtime value of a route record is a plain ``dict`` (JSON-friendly); the
``TypedDict`` definitions below document its shape and ``make_record`` /
``normalize_record`` keep every field present + clamped.

THE 6 DESTINATIONS (a.k.a. *sinks*)
-----------------------------------
- ``database``     : tabular records -> a data source (the agent queries it).
- ``semantic``     : a glossary (name -> meaning) -> column meanings.
- ``instructions`` : rules / logic prose ("X = A AND B", "always filter Y").
- ``examples``     : Q&A pairs (question -> answer / sql).
- ``knowledge``    : reference narrative (PDF/Word prose, no tables/rules).
- ``skip``         : empty / unsupported.
"""

from typing import Any, Dict, List, Optional

try:  # py>=3.8 stdlib; degrade gracefully if ever unavailable.
    from typing import TypedDict
except Exception:  # pragma: no cover
    TypedDict = dict  # type: ignore


# --------------------------------------------------------------------------- #
# Destination constants (import these — never hard-code the strings)
# --------------------------------------------------------------------------- #
DEST_DATABASE = "database"
DEST_SEMANTIC = "semantic"
DEST_INSTRUCTIONS = "instructions"
DEST_EXAMPLES = "examples"
DEST_KNOWLEDGE = "knowledge"
DEST_SKIP = "skip"

# Ordered for stable display; the catch-all fallback is ``knowledge``.
ALL_DESTS: List[str] = [
    DEST_DATABASE,
    DEST_SEMANTIC,
    DEST_INSTRUCTIONS,
    DEST_EXAMPLES,
    DEST_KNOWLEDGE,
    DEST_SKIP,
]
ALL_DESTS_SET = frozenset(ALL_DESTS)

# Map each destination to the concrete knowledge-subsystem the API layer writes
# to. ``metrics`` is not a sniff destination but is a valid downstream sink an
# operator may re-route a ``semantic`` record into — listed in the answer-
# changing set below so it stays confirm-gated.
DEST_SINKS: Dict[str, str] = {
    DEST_DATABASE: "data_source",
    DEST_SEMANTIC: "semantic_columns",
    DEST_INSTRUCTIONS: "instructions",
    DEST_EXAMPLES: "query_library",
    DEST_KNOWLEDGE: "knowledge_docs",
    DEST_SKIP: "none",
}

# Short human label per destination (UI / confirm dialog copy).
DEST_LABELS: Dict[str, str] = {
    DEST_DATABASE: "Data source (queryable table)",
    DEST_SEMANTIC: "Column meanings (glossary)",
    DEST_INSTRUCTIONS: "Instructions / rules",
    DEST_EXAMPLES: "Example Q&A pairs",
    DEST_KNOWLEDGE: "Reference knowledge",
    DEST_SKIP: "Skipped (empty / unsupported)",
}

# "Answer-changing" destinations: routing a file here can silently alter what the
# agent answers, so we confirm unless we are very sure (see classifier policy).
# ``metrics`` is included for the downstream re-route case noted above.
ANSWER_CHANGING_DESTS = frozenset(
    {DEST_SEMANTIC, DEST_INSTRUCTIONS, DEST_EXAMPLES, "metrics"}
)

# Provenance of a record's final decision.
SOURCE_HEURISTIC = "heuristic"   # fast layer only
SOURCE_ENSEMBLE = "ensemble"     # heuristic + LLM combined
SOURCE_LLM = "llm"               # LLM dominated a disagreement


# --------------------------------------------------------------------------- #
# Record shape (documented via TypedDict; runtime value is a plain dict)
# --------------------------------------------------------------------------- #
class Signals(TypedDict, total=False):
    rows: int                # data rows sampled (tabular) or 0
    cols: int                # columns sampled (tabular) or 0
    is_two_col: bool         # exactly ~2 columns, glossary-shaped
    has_rule_pattern: bool   # '=', ' AND ', must/always/filter/exclude
    has_qa: bool             # Q:/A:, Question/Answer, numbered Q&A
    has_table: bool          # a tabular grid was detected
    text_chars: int          # chars of prose extracted (text files)


class RouteRecord(TypedDict, total=False):
    filename: str
    ext: str                 # lowercased extension incl. dot, e.g. ".csv"
    dest: str                # one of ALL_DESTS
    confidence: int          # 0-100
    reason: str              # short, explainable
    sink: str                # DEST_SINKS[dest]
    signals: Signals
    needs_confirm: bool      # confirm policy result
    source: str              # SOURCE_HEURISTIC / SOURCE_ENSEMBLE / SOURCE_LLM
    disagreed: bool          # heuristic vs LLM disagreed


# --------------------------------------------------------------------------- #
# Builders / normalizers — keep every record well-formed, never throw
# --------------------------------------------------------------------------- #
def empty_signals() -> Signals:
    return {
        "rows": 0,
        "cols": 0,
        "is_two_col": False,
        "has_rule_pattern": False,
        "has_qa": False,
        "has_table": False,
        "text_chars": 0,
    }


def _clamp_conf(value: Any) -> int:
    try:
        v = int(round(float(value)))
    except Exception:
        return 0
    return max(0, min(100, v))


def make_record(
    *,
    filename: str,
    ext: str,
    dest: str,
    confidence: Any,
    reason: str = "",
    signals: Optional[Signals] = None,
    needs_confirm: Optional[bool] = None,
    source: str = SOURCE_HEURISTIC,
    disagreed: bool = False,
) -> RouteRecord:
    """Build a fully-populated, clamped route record (a plain dict)."""
    dest = dest if dest in ALL_DESTS_SET else DEST_KNOWLEDGE
    sig = empty_signals()
    if signals:
        for k, v in signals.items():
            if k in sig:
                sig[k] = v  # type: ignore[literal-required]
    rec: RouteRecord = {
        "filename": filename or "",
        "ext": (ext or "").lower(),
        "dest": dest,
        "confidence": _clamp_conf(confidence),
        "reason": (reason or "")[:300],
        "sink": DEST_SINKS.get(dest, "none"),
        "signals": sig,
        "source": source,
        "disagreed": bool(disagreed),
    }
    # needs_confirm is computed by the classifier policy unless explicitly set.
    if needs_confirm is not None:
        rec["needs_confirm"] = bool(needs_confirm)
    return rec


def normalize_record(rec: Dict[str, Any]) -> RouteRecord:
    """Coerce a loosely-built dict into a valid RouteRecord (defensive)."""
    return make_record(
        filename=str(rec.get("filename", "")),
        ext=str(rec.get("ext", "")),
        dest=str(rec.get("dest", DEST_KNOWLEDGE)),
        confidence=rec.get("confidence", 0),
        reason=str(rec.get("reason", "")),
        signals=rec.get("signals"),  # type: ignore[arg-type]
        needs_confirm=rec.get("needs_confirm"),
        source=str(rec.get("source", SOURCE_HEURISTIC)),
        disagreed=bool(rec.get("disagreed", False)),
    )
