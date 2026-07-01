"""Smart Upload classifier — the brain that decides where each file goes.

Two layers:
  1. **Fast heuristic** (`sniff_file`) — pure, no network. Detects by extension
     AND *content shape* (a small sample), returns an explainable route record.
  2. **Small-LLM tie-break** (`llm_route`) — ONE batched cheap-model call for the
     low-confidence / conflicting files only. Optional + fail-soft: with
     ``llm=None`` the whole pipeline is heuristic-only.

Contract (destinations, record shape, sinks) lives in ``contract.py`` — the API
layer imports both from there. Everything here is wrapped so a bad/unsupported
file NEVER throws: it degrades to a ``skip`` / low-confidence ``knowledge``
record instead.

LLM idiom mirrors the rest of the hybrid layer (see
``app/ai/knowledge/session_summary.py`` / ``doc_extractor.py``):
``LLM(model, usage_session_maker=async_session_maker).inference(prompt,
usage_scope=...)`` run in a worker thread. The ``llm`` argument is a **resolved
model object** (what ``LLMService().get_default_model(db, org, is_small=True)``
returns); the API layer resolves it and passes it in, so this module needs no DB.
"""

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from app.services.smart_upload import contract
from app.services.smart_upload.contract import (
    ANSWER_CHANGING_DESTS,
    ALL_DESTS_SET,
    DEST_DATABASE,
    DEST_EXAMPLES,
    DEST_INSTRUCTIONS,
    DEST_KNOWLEDGE,
    DEST_SEMANTIC,
    DEST_SKIP,
    SOURCE_ENSEMBLE,
    SOURCE_HEURISTIC,
    SOURCE_LLM,
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Tunables (conservative + explainable)
# --------------------------------------------------------------------------- #
_SAMPLE_ROWS = 50           # rows to sniff from csv/xlsx
_SAMPLE_CHARS = 4000        # chars of prose to sniff from pdf/docx/txt
_AUTO_CONF = 85             # >= this AND not answer-changing => auto (no confirm)
_ANSWER_CHANGING_AUTO = 95  # answer-changing dest needs >= this to auto

_TABULAR_EXTS = {".csv", ".tsv", ".xlsx", ".xlsm", ".xls"}
_TEXT_EXTS = {".txt", ".text", ".md", ".markdown", ".rst", ".log"}
_PDF_EXTS = {".pdf"}
_DOC_EXTS = {".docx", ".doc"}
_PPTX_EXTS = {".pptx"}

_RULE_WORDS = ("must ", " must", "always ", "filter ", "exclude ", "never ",
               "should ", "require", "only count", "only include")
_QA_PATTERNS = [
    re.compile(r"^\s*Q\s*[:\.\)]", re.I | re.M),
    re.compile(r"^\s*A\s*[:\.\)]", re.I | re.M),
    re.compile(r"^\s*Ans\s*[:\.]", re.I | re.M),
    re.compile(r"\bquestion\s*[:\-]", re.I),
    re.compile(r"\banswer\s*[:\-]", re.I),
    re.compile(r"^\s*\d+\s*[\.\)]\s.*\?", re.M),  # numbered question line
]


# --------------------------------------------------------------------------- #
# Filename hints (boost / break ties)
# --------------------------------------------------------------------------- #
def _name_hint(filename: str) -> Optional[str]:
    """Return a destination hinted by the filename, or None."""
    n = (filename or "").lower()
    if any(w in n for w in ("definition", "glossary", "dictionary", "codebook",
                            "data_dict", "data dictionary", "schema_doc")):
        return DEST_SEMANTIC
    if any(w in n for w in ("q&a", "qa", "faq", "q_and_a", "examples", "qna")):
        return DEST_EXAMPLES
    if any(w in n for w in ("logic", "rule", "rules", "sop", "policy",
                            "instruction")):
        return DEST_INSTRUCTIONS
    if any(w in n for w in ("knowledge", "reference", "manual", "guide",
                            "handbook", "readme", "notes")):
        return DEST_KNOWLEDGE
    return None


# --------------------------------------------------------------------------- #
# Sample readers — every reader is wrapped, returns (data, note) never raises
# --------------------------------------------------------------------------- #
def _read_tabular(path: str, ext: str):
    """Read first ~50 rows via pandas. Returns (DataFrame|None, note)."""
    try:
        import pandas as pd
    except Exception:
        return None, "pandas not available"
    try:
        if ext in (".csv", ".tsv"):
            sep = "\t" if ext == ".tsv" else None
            df = pd.read_csv(
                path, nrows=_SAMPLE_ROWS, sep=sep,
                engine="python", on_bad_lines="skip", dtype=str,
            )
        else:  # xlsx / xlsm / xls
            df = pd.read_excel(path, nrows=_SAMPLE_ROWS, dtype=str)
        return df, ""
    except Exception as e:
        return None, f"could not read tabular: {e}"


def _extract_text(path: str, ext: str, filename: str) -> Tuple[str, str]:
    """Extract up to ~4000 chars of prose. Returns (text, note).

    Reuses the repo's existing readers (pypdf via file_preview, doc_extractor's
    _parse_pptx) and python-docx; never adds a dependency. A missing reader
    degrades to ("", note) -> caller routes low-confidence knowledge.
    """
    try:
        if ext in _TEXT_EXTS:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                return fh.read(_SAMPLE_CHARS), ""
        if ext in _PDF_EXTS:
            try:
                from pypdf import PdfReader  # same lib file_preview uses
            except Exception:
                return "", "pypdf not installed"
            reader = PdfReader(path)
            parts: List[str] = []
            for page in reader.pages[:5]:
                try:
                    parts.append(page.extract_text() or "")
                except Exception:
                    continue
                if sum(len(p) for p in parts) >= _SAMPLE_CHARS:
                    break
            return ("\n".join(parts))[:_SAMPLE_CHARS], ""
        if ext in _DOC_EXTS:
            try:
                import docx  # python-docx
            except Exception:
                return "", "python-docx not installed"
            d = docx.Document(path)
            text = "\n".join(p.text for p in d.paragraphs)
            return text[:_SAMPLE_CHARS], ""
        if ext in _PPTX_EXTS:
            # Reuse doc_extractor's slide-text parser.
            try:
                from app.ai.knowledge.doc_extractor import _parse_pptx
                parsed = _parse_pptx(path)
                if "error" in parsed:
                    return "", parsed["error"]
                return (parsed.get("digest") or "")[:_SAMPLE_CHARS], ""
            except Exception as e:
                return "", f"pptx parse failed: {e}"
    except Exception as e:
        return "", f"text extract failed: {e}"
    return "", "unsupported text type"


# --------------------------------------------------------------------------- #
# Shape detectors
# --------------------------------------------------------------------------- #
def _numeric_col_count(df) -> int:
    """Count columns where a majority of sampled cells parse as numbers."""
    try:
        import pandas as pd
    except Exception:
        return 0
    n = 0
    for col in df.columns:
        ser = df[col].dropna()
        if len(ser) == 0:
            continue
        coerced = pd.to_numeric(ser, errors="coerce")
        if coerced.notna().mean() >= 0.6:
            n += 1
    return n


def _two_col_glossary(df) -> Tuple[bool, int]:
    """Detect a (term -> definition) 2-col glossary.

    Returns (is_glossary, pair_count). Heuristic: exactly ~2 columns, >=3
    non-empty pairs, mean(len(right)) clearly > mean(len(left)), and the left
    column reads like short tokens (mean len small).
    """
    try:
        ncols = df.shape[1]
        if ncols != 2:
            return False, 0
        left = df.iloc[:, 0].dropna().astype(str).map(str.strip)
        right = df.iloc[:, 1].dropna().astype(str).map(str.strip)
        pairs = min(len(left), len(right))
        if pairs < 3:
            return False, pairs
        ml = left.map(len).mean()
        mr = right.map(len).mean()
        if ml and mr and mr > (ml * 1.5) and ml <= 40 and mr >= 15:
            return True, pairs
        return False, pairs
    except Exception:
        return False, 0


def _has_rule_pattern(text: str) -> bool:
    low = "\n" + text.lower()
    if " and " in low and "=" in text:
        return True
    if re.search(r"^\s*<?[\w \-/]{2,40}>?\s*=\s*.+", text, re.M):
        return True  # "<Term> = <condition>"
    return any(w in low for w in _RULE_WORDS)


def _has_qa(text: str) -> bool:
    hits = sum(1 for pat in _QA_PATTERNS if pat.search(text))
    return hits >= 1


# --------------------------------------------------------------------------- #
# 1. sniff_file — the fast heuristic layer (pure, never throws)
# --------------------------------------------------------------------------- #
def sniff_file(path: str, filename: str) -> Dict[str, Any]:
    """Classify one file by extension + content shape. Returns a RouteRecord."""
    try:
        fname = filename or (os.path.basename(path) if path else "")
        ext = os.path.splitext(fname or (path or ""))[1].lower()
        hint = _name_hint(fname)

        # Unsupported / missing file -> skip.
        if not path or not os.path.exists(path):
            return contract.make_record(
                filename=fname, ext=ext, dest=DEST_SKIP, confidence=90,
                reason="file not found", source=SOURCE_HEURISTIC,
            )
        if os.path.getsize(path) == 0:
            return contract.make_record(
                filename=fname, ext=ext, dest=DEST_SKIP, confidence=95,
                reason="empty file", source=SOURCE_HEURISTIC,
            )

        if ext in _TABULAR_EXTS:
            return _sniff_tabular(path, ext, fname, hint)
        if ext in _TEXT_EXTS | _PDF_EXTS | _DOC_EXTS | _PPTX_EXTS:
            return _sniff_text(path, ext, fname, hint)

        # Unknown binary -> degrade to low-confidence knowledge (noted).
        return contract.make_record(
            filename=fname, ext=ext, dest=DEST_KNOWLEDGE, confidence=35,
            reason=f"unrecognized type '{ext or '?'}' — no reader, treating as "
                   f"reference (low confidence)",
            source=SOURCE_HEURISTIC,
        )
    except Exception as e:  # absolute belt-and-suspenders
        logger.warning("sniff_file failed for %s: %s", filename, e)
        return contract.make_record(
            filename=filename or "", ext="", dest=DEST_SKIP, confidence=0,
            reason=f"sniff error: {e}", source=SOURCE_HEURISTIC,
        )


def _sniff_tabular(path, ext, fname, hint) -> Dict[str, Any]:
    df, note = _read_tabular(path, ext)
    if df is None or df.shape[1] == 0:
        return contract.make_record(
            filename=fname, ext=ext, dest=DEST_SKIP, confidence=60,
            reason=note or "no tabular content", source=SOURCE_HEURISTIC,
            signals={"has_table": False},
        )
    rows, cols = int(df.shape[0]), int(df.shape[1])
    is_glossary, pairs = _two_col_glossary(df)
    num_cols = _numeric_col_count(df)
    sig = {
        "rows": rows, "cols": cols, "is_two_col": (cols == 2),
        "has_table": True, "has_rule_pattern": False, "has_qa": False,
        "text_chars": 0,
    }

    # Glossary (2-col term->definition) wins over database when shape matches,
    # OR when the filename explicitly hints semantic and it's a 2-col-ish sheet.
    if is_glossary or (hint == DEST_SEMANTIC and cols in (2, 3) and rows >= 3):
        conf = 90 if (is_glossary and hint == DEST_SEMANTIC) else \
            (84 if is_glossary else 72)
        return contract.make_record(
            filename=fname, ext=ext, dest=DEST_SEMANTIC, confidence=conf,
            reason=f"2-column glossary shape ({pairs} term->definition pairs, "
                   f"right column is prose)",
            signals=sig, source=SOURCE_HEURISTIC,
        )

    # Database: enough rows + columns + at least one numeric/measure column.
    if rows >= 8 and cols >= 2 and num_cols >= 1:
        return contract.make_record(
            filename=fname, ext=ext, dest=DEST_DATABASE, confidence=90,
            reason=f"tabular records ({rows}+ rows x {cols} cols, "
                   f"{num_cols} numeric column(s))",
            signals=sig, source=SOURCE_HEURISTIC,
        )

    # Small / non-numeric table -> still a data source but lower confidence.
    if rows >= 2 and cols >= 2:
        return contract.make_record(
            filename=fname, ext=ext, dest=DEST_DATABASE, confidence=66,
            reason=f"small table ({rows} rows x {cols} cols, "
                   f"{num_cols} numeric) — likely a data source, please confirm",
            signals=sig, source=SOURCE_HEURISTIC,
        )

    return contract.make_record(
        filename=fname, ext=ext, dest=DEST_SKIP, confidence=55,
        reason="too few rows/cols to be a useful table",
        signals=sig, source=SOURCE_HEURISTIC,
    )


def _sniff_text(path, ext, fname, hint) -> Dict[str, Any]:
    text, note = _extract_text(path, ext, fname)
    chars = len(text or "")
    if chars == 0:
        # No extractable text -> degrade to low-confidence knowledge.
        return contract.make_record(
            filename=fname, ext=ext, dest=DEST_KNOWLEDGE, confidence=30,
            reason=note or "no extractable text — treating as reference "
                           "(low confidence)",
            signals={"text_chars": 0}, source=SOURCE_HEURISTIC,
        )

    has_qa = _has_qa(text)
    has_rule = _has_rule_pattern(text)
    sig = {
        "rows": 0, "cols": 0, "is_two_col": False, "has_table": False,
        "has_rule_pattern": has_rule, "has_qa": has_qa, "text_chars": chars,
    }

    # Examples (Q&A) — strongest signal; filename hint boosts.
    if has_qa:
        conf = 90 if hint == DEST_EXAMPLES else 82
        return contract.make_record(
            filename=fname, ext=ext, dest=DEST_EXAMPLES, confidence=conf,
            reason="question/answer pairs detected (Q:/A: or numbered Q&A)",
            signals=sig, source=SOURCE_HEURISTIC,
        )

    # Instructions (rules / logic prose).
    if has_rule:
        conf = 88 if hint == DEST_INSTRUCTIONS else 80
        return contract.make_record(
            filename=fname, ext=ext, dest=DEST_INSTRUCTIONS, confidence=conf,
            reason="rule/logic patterns detected "
                   "('=', ' AND ', must/always/filter/exclude)",
            signals=sig, source=SOURCE_HEURISTIC,
        )

    # Filename hints with no strong content signal.
    if hint in (DEST_SEMANTIC, DEST_EXAMPLES, DEST_INSTRUCTIONS):
        return contract.make_record(
            filename=fname, ext=ext, dest=hint, confidence=68,
            reason=f"filename hints '{hint}' (no strong content signal)",
            signals=sig, source=SOURCE_HEURISTIC,
        )

    # Default: narrative reference -> knowledge.
    conf = 86 if (chars >= 400 and hint in (None, DEST_KNOWLEDGE)) else 74
    return contract.make_record(
        filename=fname, ext=ext, dest=DEST_KNOWLEDGE, confidence=conf,
        reason="narrative prose, no table / rule / Q&A pattern",
        signals=sig, source=SOURCE_HEURISTIC,
    )


# --------------------------------------------------------------------------- #
# 4. Confirm policy
# --------------------------------------------------------------------------- #
def _needs_confirm(rec: Dict[str, Any]) -> bool:
    """True if a human should confirm this routing before it takes effect.

    Confirm when: confidence < 85, OR the classifiers disagreed, OR the
    destination is answer-changing (semantic/instructions/examples/metrics) and
    confidence < 95. Otherwise auto (database/knowledge high-confidence).
    """
    try:
        conf = int(rec.get("confidence", 0))
        if conf < _AUTO_CONF:
            return True
        if rec.get("disagreed"):
            return True
        if rec.get("dest") in ANSWER_CHANGING_DESTS and conf < _ANSWER_CHANGING_AUTO:
            return True
        return False
    except Exception:
        return True


def _apply_confirm(rec: Dict[str, Any]) -> Dict[str, Any]:
    rec["needs_confirm"] = _needs_confirm(rec)
    return rec


# --------------------------------------------------------------------------- #
# 3. LLM tie-break (P2) — ONE batched cheap call, fail-soft
# --------------------------------------------------------------------------- #
_DEST_MENU = (
    "database   = tabular records to query (a data source)\n"
    "semantic   = a glossary mapping column/term -> its meaning\n"
    "instructions = rules / logic prose (e.g. 'X = A AND B', 'always filter Y')\n"
    "examples   = question/answer pairs (Q -> answer or SQL)\n"
    "knowledge  = reference narrative prose (no tables, no rules, no Q&A)\n"
    "skip       = empty or unsupported"
)


def _build_route_prompt(samples: List[Dict[str, Any]],
                        excerpt_chars: int = 600) -> str:
    lines = [
        "You route uploaded files to ONE destination each. Destinations:",
        _DEST_MENU,
        "",
        "For each file below, decide the single best destination, a confidence "
        "0-100, and a short reason. Use the filename AND the content excerpt.",
        "",
    ]
    for i, s in enumerate(samples, 1):
        excerpt = (s.get("excerpt") or "").replace("\r", " ")
        excerpt = re.sub(r"[ \t]+", " ", excerpt)[:max(200, int(excerpt_chars or 600))]
        lines.append(f"FILE {i}: name={s.get('filename','')!r}")
        lines.append(f"EXCERPT: {excerpt}")
        lines.append("")
    lines.append(
        'Return STRICT JSON only, no prose, no code fence:\n'
        '{"results":[{"filename":"...","dest":"database|semantic|instructions|'
        'examples|knowledge|skip","confidence":0-100,"reason":"..."}]}'
    )
    return "\n".join(lines)


def _parse_route_json(raw: str) -> Dict[str, Dict[str, Any]]:
    """Parse the model reply into {filename: {dest,confidence,reason}}."""
    if not raw:
        return {}
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1:]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    try:
        obj = json.loads(text, strict=False)
    except Exception:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    results = obj.get("results") if isinstance(obj, dict) else None
    if not isinstance(results, list):
        return {}
    for r in results:
        if not isinstance(r, dict):
            continue
        fn = str(r.get("filename", "")).strip()
        dest = str(r.get("dest", "")).strip().lower()
        if not fn or dest not in ALL_DESTS_SET:
            continue
        try:
            conf = max(0, min(100, int(round(float(r.get("confidence", 0))))))
        except Exception:
            conf = 0
        out[fn] = {"dest": dest, "confidence": conf,
                   "reason": str(r.get("reason", ""))[:300]}
    return out


async def llm_route(samples: List[Dict[str, Any]], llm, organization=None,
                    excerpt_chars: int = 600) -> Dict[str, Dict[str, Any]]:
    """ONE batched small-model call. Returns {filename: {dest,confidence,reason}}.

    ``llm`` is a resolved model object (as returned by
    ``LLMService().get_default_model(db, org, is_small=True)``). Returns ``{}``
    on any error or when ``llm`` is None — the caller treats that as a no-op
    and falls back to the heuristic. NEVER raises.
    """
    if not samples or llm is None:
        return {}
    try:
        prompt = _build_route_prompt(samples, excerpt_chars=excerpt_chars)

        def _infer() -> str:
            from app.ai.llm.llm import LLM
            from app.dependencies import async_session_maker
            return LLM(llm, usage_session_maker=async_session_maker).inference(
                prompt, usage_scope="smart_upload_route"
            )

        raw = await asyncio.to_thread(_infer)
        return _parse_route_json(raw or "")
    except Exception as e:
        logger.warning("smart_upload llm_route failed: %s", e)
        return {}


# --------------------------------------------------------------------------- #
# 2. classify_batch — orchestrate heuristic + optional LLM ensemble
# --------------------------------------------------------------------------- #
def _excerpt_for(rec: Dict[str, Any], path: str, excerpt_chars: int = 600) -> str:
    """Build a content excerpt for the LLM from the file.

    ``excerpt_chars`` caps the excerpt length: ~600 for the live (latency-bound)
    upload path, much larger (e.g. 4000) at train time where a sharper read on
    borderline files is worth the extra tokens.
    """
    cap = max(200, int(excerpt_chars or 600))
    ext = rec.get("ext", "")
    try:
        if ext in _TABULAR_EXTS:
            df, _ = _read_tabular(path, ext)
            if df is not None:
                rows = 8 if cap <= 600 else 25
                head = df.head(rows).to_csv(index=False)
                return head[:cap]
            return ""
        text, _ = _extract_text(path, ext, rec.get("filename", ""))
        return (text or "")[:cap]
    except Exception:
        return ""


async def classify_batch(files: List[Dict[str, Any]], llm=None,
                         organization=None,
                         excerpt_chars: int = 600) -> List[Dict[str, Any]]:
    """Classify a batch of files. ``files`` = [{path, filename}, ...].

    Runs the heuristic on every file. Any record with confidence < 85 OR
    conflicting signals is sent (batched) to ``llm_route`` for a tie-break —
    only when ``llm`` is provided. With ``llm=None`` this is heuristic-only.
    Ensemble rules:
      * agree   -> confidence = max(heuristic, llm); confirm per policy.
      * disagree-> keep the higher-confidence destination, set disagreed=True
                   (=> needs_confirm True via policy).
    Fail-soft: any LLM error leaves the heuristic record (low-conf ones already
    flagged for confirm). NEVER raises.
    """
    records: List[Dict[str, Any]] = []
    paths: List[str] = []
    for f in files or []:
        path = (f or {}).get("path", "")
        filename = (f or {}).get("filename", "") or (
            os.path.basename(path) if path else "")
        rec = sniff_file(path, filename)
        records.append(rec)
        paths.append(path)

    # Decide who needs the LLM tie-break.
    tiebreak_idx: List[int] = []
    for i, rec in enumerate(records):
        if _is_uncertain(rec):
            tiebreak_idx.append(i)

    if llm is not None and tiebreak_idx:
        samples = [
            {"filename": records[i].get("filename", ""),
             "excerpt": _excerpt_for(records[i], paths[i], excerpt_chars)}
            for i in tiebreak_idx
        ]
        llm_map = await llm_route(samples, llm, organization,
                                  excerpt_chars=excerpt_chars)
        for i in tiebreak_idx:
            fn = records[i].get("filename", "")
            llm_res = llm_map.get(fn)
            if not llm_res:
                continue  # LLM said nothing for this file -> keep heuristic
            records[i] = _ensemble(records[i], llm_res)

    # Stamp the confirm policy on every record (heuristic-only path too).
    return [_apply_confirm(r) for r in records]


def _is_uncertain(rec: Dict[str, Any]) -> bool:
    """Low confidence OR conflicting signals -> wants an LLM tie-break."""
    try:
        if int(rec.get("confidence", 0)) < _AUTO_CONF:
            return True
        sig = rec.get("signals", {}) or {}
        # Conflicting signals: e.g. a text file showing BOTH rule and Q&A
        # patterns, or a tabular file that is both glossary-shaped and numeric.
        if sig.get("has_rule_pattern") and sig.get("has_qa"):
            return True
        return False
    except Exception:
        return True


def _ensemble(heur: Dict[str, Any], llm_res: Dict[str, Any]) -> Dict[str, Any]:
    """Combine a heuristic record with the LLM's verdict for one file."""
    h_conf = int(heur.get("confidence", 0))
    l_conf = int(llm_res.get("confidence", 0))
    l_dest = llm_res.get("dest")
    l_reason = llm_res.get("reason", "")

    if l_dest == heur.get("dest"):
        # Agree -> reinforce, take the higher confidence.
        return contract.make_record(
            filename=heur.get("filename", ""), ext=heur.get("ext", ""),
            dest=heur.get("dest"), confidence=max(h_conf, l_conf),
            reason=heur.get("reason", ""), signals=heur.get("signals"),
            source=SOURCE_ENSEMBLE, disagreed=False,
        )

    # Disagree -> keep the higher-confidence destination, flag for confirm.
    if l_conf > h_conf:
        return contract.make_record(
            filename=heur.get("filename", ""), ext=heur.get("ext", ""),
            dest=l_dest, confidence=l_conf,
            reason=f"LLM: {l_reason} (heuristic said {heur.get('dest')})",
            signals=heur.get("signals"), source=SOURCE_LLM, disagreed=True,
        )
    return contract.make_record(
        filename=heur.get("filename", ""), ext=heur.get("ext", ""),
        dest=heur.get("dest"), confidence=h_conf,
        reason=f"{heur.get('reason','')} (LLM disagreed: {l_dest})",
        signals=heur.get("signals"), source=SOURCE_ENSEMBLE, disagreed=True,
    )
