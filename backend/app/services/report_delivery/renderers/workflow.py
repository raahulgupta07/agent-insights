"""Mode C — automation / workflow run output.

Emails the OUTPUT of a workflow / automation run: a step TIMELINE (each step a
✓ / ✗ / • glyph + its title), a one-line "N/total steps completed" summary, a
short sanitized intro, and any per-step output files attached.

WHAT A "WORKFLOW RUN" IS HERE
-----------------------------
The workflow subsystem (`app/ai/workflows/`) is a *pure deterministic engine*:
`run_pipeline` fans a work-list through a stage worker gated by a verifier and
returns a SUMMARY dict — it never raises::

    {label, processed, passed, skipped, failed,
     log:    [{item, status, attempts, reason, result_summary}, ...],
     results:[<kept stage result>, ...]}

where each log entry's ``status`` is one of ``passed`` / ``skipped`` /
``failed``. The HTTP surface (`routes/workflows.py`) is explicit that there is
**NO persisted run table** — runs are synchronous and the only record is an
in-process ``_LAST_RUNS[name]`` dict of shape::

    {status, name, summary:<the engine dict above>, finished_at} | {status:"error", ...}

So this renderer resolves a run in priority order, then DEGRADES GRACEFULLY:

  1. an inline run/summary handed in via ``ctx.options``
     (``workflow_run`` | ``run`` | ``summary``), OR
  2. the last in-process run for a named workflow
     (``ctx.options['workflow_name' | 'workflow' | 'name']`` → ``_LAST_RUNS``), OR
  3. ``ctx.exec_summary`` (``{iterations, queries, artifacts, last_content}``)
     synthesised into a tiny single-step timeline, OR
  4. nothing → a fail-soft "No workflow run details available." body.

It accepts BOTH the engine summary shape AND a generic ``{steps:[...]}`` /
``{name,status,output_files}`` shape, so a future workflow that *does* persist
per-step files attaches them for free. NEVER raises.
"""
from __future__ import annotations

import html as _h
import logging
import mimetypes
import os

from app.services.report_delivery.contract import (
    Attachment,
    DeliveryContext,
    DeliveryParts,
    register_renderer,
)
from app.services.report_delivery import extract, template

logger = logging.getLogger(__name__)

# ---- caps (email-safe) ----------------------------------------------------
_MAX_ATTACHMENTS = 10
_MAX_TOTAL_BYTES = 25 * 1024 * 1024          # ~25 MB across all outputs
_MAX_ONE_BYTES = 20 * 1024 * 1024            # skip any single output > 20 MB

# status -> (glyph, colour). Anything else falls back to the neutral bullet.
_GLYPHS = {
    "passed": ("✓", "#1a7f37"),   # ✓ green
    "success": ("✓", "#1a7f37"),
    "ok": ("✓", "#1a7f37"),
    "done": ("✓", "#1a7f37"),
    "completed": ("✓", "#1a7f37"),
    "failed": ("✗", "#c0362c"),   # ✗ red
    "error": ("✗", "#c0362c"),
    "skipped": ("—", "#9a958c"),  # — muted (gate rejected, not a failure)
}
_OTHER = ("•", "#9a958c")         # • neutral


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------
async def render(ctx: DeliveryContext) -> DeliveryParts:
    title = ctx.title or "Workflow report"
    meta = "Automated workflow · agent report"
    footer = "Generated automatically and delivered via this agent's email."

    try:
        run = _resolve_run(ctx)
    except Exception:  # noqa: BLE001 — resolution must never break the send
        logger.debug("workflow renderer: run resolution failed", exc_info=True)
        run = None

    # 1. intro paragraph from the agent's prose (sanitized), with a sensible
    #    fallback so the email is never intro-less.
    intro = await _build_intro(ctx)

    # 2. fail-soft: no run AND no exec_summary signal -> note + whatever we have.
    if not run:
        inner = (
            f"<p style='font-size:14px;margin:0 0 4px'>{intro}</p>"
            + _note_html("No workflow run details available.")
            + _exec_summary_html(ctx.exec_summary)
        )
        body = template.skeleton(
            title=title, meta=meta, inner_html=inner,
            report_url=ctx.report_url, footer=footer,
        )
        return DeliveryParts(body_html=body, subject=title)

    steps = run.get("steps") or []
    summary_line = _summary_line(run, steps)
    timeline = _timeline_html(steps)

    # 3. collect per-step output files (capped).
    attachments, overflow = _collect_attachments(steps, run)
    overflow_note = (
        _note_html(f"+{overflow} more output{'s' if overflow != 1 else ''} not attached.")
        if overflow else ""
    )

    inner = (
        f"<p style='font-size:14px;margin:0 0 4px'>{intro}</p>"
        + timeline
        + summary_line
        + overflow_note
    )

    body = template.skeleton(
        title=title, meta=meta, inner_html=inner,
        report_url=ctx.report_url, footer=footer,
    )
    return DeliveryParts(body_html=body, attachments=attachments, subject=title)


# ---------------------------------------------------------------------------
# run resolution  ->  a normalised {steps:[{title,status,files:[...]}], counts}
# ---------------------------------------------------------------------------
def _resolve_run(ctx: DeliveryContext) -> dict | None:
    opt = ctx.options or {}

    # (1) inline run / summary handed straight in.
    for key in ("workflow_run", "run", "summary"):
        raw = opt.get(key)
        if isinstance(raw, dict) and raw:
            norm = _normalise_run(raw)
            if norm:
                return norm

    # (2) last in-process run for a named workflow.
    name = opt.get("workflow_name") or opt.get("workflow") or opt.get("name")
    if isinstance(name, str) and name:
        rec = _last_run_for(name)
        if isinstance(rec, dict) and rec:
            # _LAST_RUNS stores {status,name,summary,...} | {status:'error',error}.
            payload = rec.get("summary") if isinstance(rec.get("summary"), dict) else rec
            norm = _normalise_run(payload)
            if norm:
                return norm

    # (3) synthesise a single-step run from exec_summary, if it carries signal.
    return _run_from_exec_summary(ctx.exec_summary)


def _last_run_for(name: str) -> dict | None:
    """Read the in-process last-run store from the workflows route. Best-effort:
    the store is process-local + ephemeral, so a miss is normal."""
    try:
        from app.routes import workflows as _wf  # type: ignore
        return (_wf._LAST_RUNS or {}).get(name)
    except Exception:  # noqa: BLE001
        return None


def _normalise_run(raw: dict) -> dict | None:
    """Coerce any supported run shape into {steps:[{title,status,files}], ...}.

    Supported inputs:
      - engine summary: {log:[{item,status,reason,result_summary}], passed,...}
      - generic:        {steps:[{title|name, status, output_files|files|outputs}]}
      - single result:  {name|title, status, output_files}
    """
    if not isinstance(raw, dict):
        return None

    steps: list[dict] = []

    # generic explicit steps list ------------------------------------------
    raw_steps = raw.get("steps")
    if isinstance(raw_steps, (list, tuple)) and raw_steps:
        for s in raw_steps:
            st = _normalise_step(s)
            if st:
                steps.append(st)

    # engine log entries ----------------------------------------------------
    if not steps:
        log = raw.get("log")
        if isinstance(log, (list, tuple)) and log:
            for i, e in enumerate(log, 1):
                st = _normalise_log_entry(e, i)
                if st:
                    steps.append(st)

    # a single result object treated as one step ---------------------------
    if not steps and (raw.get("name") or raw.get("title")) and raw.get("status"):
        st = _normalise_step(raw)
        if st:
            steps.append(st)

    if not steps:
        return None

    return {
        "steps": steps,
        "label": raw.get("label") or raw.get("name") or "",
        "note": raw.get("note") or raw.get("error") or "",
    }


def _normalise_step(s) -> dict | None:
    if not isinstance(s, dict):
        # a bare title string is still a step
        if isinstance(s, str) and s.strip():
            return {"title": _trim(s), "status": "", "files": []}
        return None
    title = (
        s.get("title") or s.get("name") or s.get("label")
        or s.get("step") or s.get("item") or "Step"
    )
    status = str(s.get("status") or s.get("state") or s.get("result") or "").strip().lower()
    files = _files_from(s)
    return {"title": _trim(str(title)), "status": status, "files": files}


def _normalise_log_entry(e, idx: int) -> dict | None:
    if not isinstance(e, dict):
        return None
    title = e.get("item") or e.get("title") or e.get("name") or f"Step {idx}"
    status = str(e.get("status") or "").strip().lower()
    reason = e.get("reason") or e.get("result_summary") or ""
    label = _trim(str(title))
    if reason:
        label = f"{label} — {_trim(str(reason), 90)}"
    return {"title": label, "status": status, "files": _files_from(e)}


def _run_from_exec_summary(exec_summary) -> dict | None:
    """Degrade gracefully: turn the scheduled-run exec_summary into a one-row
    timeline so a workflow-mode email still shows *something* structured."""
    if not isinstance(exec_summary, dict) or not exec_summary:
        return None
    iters = _int(exec_summary.get("iterations"))
    queries = _int(exec_summary.get("queries"))
    artifacts = _int(exec_summary.get("artifacts"))
    last = exec_summary.get("last_content")
    if not (iters or queries or artifacts or last):
        return None
    bits = []
    if iters:
        bits.append(f"{iters} step{'s' if iters != 1 else ''}")
    if queries:
        bits.append(f"{queries} quer{'ies' if queries != 1 else 'y'}")
    if artifacts:
        bits.append(f"{artifacts} artifact{'s' if artifacts != 1 else ''}")
    title = "Workflow run completed"
    if bits:
        title += " — " + ", ".join(bits)
    return {
        "steps": [{"title": title, "status": "passed", "files": []}],
        "label": "",
        "note": "",
    }


# ---------------------------------------------------------------------------
# output-file collection
# ---------------------------------------------------------------------------
def _files_from(obj) -> list[dict]:
    """Pull a list of file descriptors off a step/result dict. Each descriptor
    is normalised to {filename, path?|content?|bytes?, mime?}. Best-effort."""
    if not isinstance(obj, dict):
        return []
    out: list[dict] = []
    for key in ("output_files", "outputs", "files", "artifacts", "attachments"):
        val = obj.get(key)
        if isinstance(val, (list, tuple)):
            for f in val:
                d = _normalise_file(f)
                if d:
                    out.append(d)
        elif isinstance(val, (dict, str)):
            d = _normalise_file(val)
            if d:
                out.append(d)
    return out


def _normalise_file(f) -> dict | None:
    if isinstance(f, str):
        # a bare path string
        return {"path": f, "filename": os.path.basename(f) or "output"}
    if not isinstance(f, dict):
        return None
    path = f.get("path") or f.get("file") or f.get("filepath") or f.get("url")
    content = f.get("content") or f.get("bytes") or f.get("data")
    filename = (
        f.get("filename") or f.get("name")
        or (os.path.basename(path) if isinstance(path, str) else None)
        or "output"
    )
    mime = f.get("mime") or f.get("mime_type") or f.get("content_type")
    if not (path or isinstance(content, (bytes, bytearray))):
        return None
    return {"path": path, "content": content, "filename": filename, "mime": mime}


def _collect_attachments(steps: list[dict], run: dict) -> tuple[list[Attachment], int]:
    """Read per-step output files into Attachments, honouring count + size caps.
    Returns (attachments, overflow_count). Never raises."""
    attachments: list[Attachment] = []
    total = 0
    overflow = 0
    descriptors: list[dict] = []
    for st in steps:
        descriptors.extend(st.get("files") or [])
    # run-level files too (some shapes attach at the run, not the step)
    descriptors.extend(_files_from(run))

    for d in descriptors:
        if len(attachments) >= _MAX_ATTACHMENTS:
            overflow += 1
            continue
        try:
            data = _read_bytes(d)
        except Exception:  # noqa: BLE001
            logger.debug("workflow renderer: could not read output file", exc_info=True)
            data = None
        if not data:
            continue
        if len(data) > _MAX_ONE_BYTES or total + len(data) > _MAX_TOTAL_BYTES:
            overflow += 1
            continue
        maintype, subtype = _split_mime(d.get("filename"), d.get("mime"))
        attachments.append(Attachment(
            filename=_safe_filename(d.get("filename")),
            content=data, mime_type=maintype, mime_subtype=subtype,
        ))
        total += len(data)
    return attachments, overflow


def _read_bytes(d: dict) -> bytes | None:
    content = d.get("content")
    if isinstance(content, (bytes, bytearray)):
        return bytes(content)
    if isinstance(content, str):
        # could be base64 or raw text — try base64, else utf-8 bytes
        try:
            import base64
            return base64.b64decode(content, validate=True)
        except Exception:
            return content.encode("utf-8", "replace")
    path = d.get("path")
    if isinstance(path, str) and path and not path.startswith(("http://", "https://")):
        if os.path.isfile(path) and os.path.getsize(path) <= _MAX_ONE_BYTES:
            with open(path, "rb") as fh:
                return fh.read()
    return None


# ---------------------------------------------------------------------------
# HTML pieces
# ---------------------------------------------------------------------------
def _timeline_html(steps: list[dict]) -> str:
    if not steps:
        return ""
    rows = ""
    for st in steps:
        glyph, colour = _GLYPHS.get(st.get("status") or "", _OTHER)
        title = _h.escape(st.get("title") or "Step")
        n_files = len(st.get("files") or [])
        files_badge = (
            f"<span style='color:#9a958c;font-size:12px'> &nbsp;· {n_files} "
            f"output{'s' if n_files != 1 else ''}</span>"
            if n_files else ""
        )
        rows += (
            "<div style='display:flex;align-items:baseline;padding:6px 0;"
            "border-bottom:1px solid #f0ede7'>"
            f"<span style='color:{colour};font-weight:bold;font-size:15px;"
            f"width:20px;flex:0 0 20px;text-align:center'>{glyph}</span>"
            f"<span style='font-size:13.5px;color:#222'>{title}{files_badge}</span>"
            "</div>"
        )
    return (
        "<h3 style='margin:20px 0 6px;font-size:15px;"
        "font-family:Segoe UI,Arial,sans-serif'>Steps</h3>"
        "<div style='font-family:Segoe UI,Arial,sans-serif'>" + rows + "</div>"
    )


def _summary_line(run: dict, steps: list[dict]) -> str:
    total = len(steps)
    done = sum(1 for s in steps if (s.get("status") or "") in _GLYPHS
               and _GLYPHS[s["status"]][0] == "✓")
    label = _h.escape(run.get("label") or "")
    prefix = f"{label}: " if label else ""
    return (
        "<p style='margin:10px 0 0;font-size:13px;color:#555'>"
        f"{prefix}{done}/{total} step{'s' if total != 1 else ''} completed.</p>"
    )


def _note_html(text: str) -> str:
    return (
        "<p style='margin:14px 0 0;font-size:13px;color:#9a958c;"
        f"font-style:italic'>{_h.escape(text)}</p>"
    )


def _exec_summary_html(exec_summary) -> str:
    """A minimal stat line from exec_summary for the no-run fail-soft path."""
    if not isinstance(exec_summary, dict) or not exec_summary:
        return ""
    iters = _int(exec_summary.get("iterations"))
    queries = _int(exec_summary.get("queries"))
    artifacts = _int(exec_summary.get("artifacts"))
    if not (iters or queries or artifacts):
        return ""
    bits = []
    if iters:
        bits.append(f"{iters} step{'s' if iters != 1 else ''}")
    if queries:
        bits.append(f"{queries} quer{'ies' if queries != 1 else 'y'}")
    if artifacts:
        bits.append(f"{artifacts} artifact{'s' if artifacts != 1 else ''}")
    return (
        "<p style='margin:8px 0 0;font-size:13px;color:#555'>"
        f"Run produced {', '.join(bits)}.</p>"
    )


async def _build_intro(ctx: DeliveryContext) -> str:
    fallback = "Your automated workflow finished. Summary below."
    try:
        raw = await extract.latest_narrative(ctx.report_id)
        narrative = extract.sanitize_chat_content(raw)
        intro, _insights = extract.split_intro_and_insights(narrative)
        return intro or fallback
    except Exception:  # noqa: BLE001
        logger.debug("workflow renderer: intro build failed", exc_info=True)
        return fallback


# ---------------------------------------------------------------------------
# small utils
# ---------------------------------------------------------------------------
def _trim(s: str, limit: int = 140) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _int(v) -> int:
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _safe_filename(name) -> str:
    base = os.path.basename(str(name or "output")).strip() or "output"
    # drop anything obviously path-ish / control
    return "".join(c for c in base if c.isprintable() and c not in "\\/").strip() or "output"


def _split_mime(filename, mime) -> tuple[str, str]:
    """Return (maintype, subtype) for an Attachment. Falls back to
    application/octet-stream."""
    guess = None
    if isinstance(mime, str) and "/" in mime:
        guess = mime
    elif isinstance(filename, str):
        guess = mimetypes.guess_type(filename)[0]
    if guess and "/" in guess:
        maintype, _, subtype = guess.partition("/")
        return maintype or "application", subtype or "octet-stream"
    return "application", "octet-stream"


register_renderer("workflow", render)
