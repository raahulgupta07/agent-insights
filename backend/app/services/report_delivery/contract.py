"""Frozen contract for the universal report-delivery layer.

This is the ONLY interface P3/P4/P5 renderers depend on, so it must stay stable
once P1 ships. Renderers return :class:`DeliveryParts`; the assembler (P1) wraps
them in the shared template and hands the result to the per-agent SMTP resolver.

Modes (registered by their own phases, all optional at P0):
    "result"    A — single query result (table + insights)        [P1]
    "dashboard" B — multi-widget dashboard (inline PNG + PDF)      [P3]
    "artifact"  D — PPTX/PDF artifact (page-1 preview + file)      [P4]
    "workflow"  C — automation/workflow run output                 [P5]
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class InlineImage:
    """An image embedded in the HTML body via a ``cid:`` reference."""
    cid: str                      # referenced as <img src="cid:{cid}">
    content: bytes
    mime_subtype: str = "png"     # png | jpeg
    filename: Optional[str] = None


@dataclass
class Attachment:
    """A file attached to the email (pdf, xlsx, csv, pptx…)."""
    filename: str
    content: bytes
    mime_type: str = "application"
    mime_subtype: str = "octet-stream"


@dataclass
class DeliveryContext:
    """Everything a renderer needs to build its parts.

    Deliberately plain — no ORM objects — so renderers can be unit-tested and so
    P3/P4/P5 don't have to thread session/model imports through the contract.
    """
    report_id: str
    organization_id: str
    studio_id: Optional[str] = None
    title: str = "Report"
    report_url: Optional[str] = None
    locale: Optional[str] = None
    # exec_summary from the scheduled run: {iterations, queries, artifacts, last_content}
    exec_summary: dict = field(default_factory=dict)
    # free-form per-mode options (format choice, recipient hints, etc.)
    options: dict = field(default_factory=dict)


@dataclass
class DeliveryParts:
    """What a renderer returns. The assembler owns the surrounding skeleton
    (title bar, footer, branding); a renderer only fills the body + payloads."""
    body_html: str = ""
    inline_images: list[InlineImage] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    # optional one-line subject hint; assembler falls back to ctx.title
    subject: Optional[str] = None


# Renderer = (DeliveryContext) -> DeliveryParts  (may be async; assembler awaits)
Renderer = Callable[[DeliveryContext], "DeliveryParts"]

_RENDERERS: dict[str, Renderer] = {}


def register_renderer(mode: str, renderer: Renderer) -> None:
    """Register a mode renderer. Idempotent last-wins so a phase can re-import."""
    _RENDERERS[mode] = renderer


def get_renderer(mode: str) -> Optional[Renderer]:
    return _RENDERERS.get(mode)


def list_modes() -> list[str]:
    return sorted(_RENDERERS.keys())


async def classify(ctx: DeliveryContext) -> str:
    """Pick a mode key for ``ctx``. Async + DB-aware; fail-soft to "result".

    Priority:
      1. explicit ``options.format`` / ``options.mode`` hint (dashboard|table|...)
      2. workflow source (``options.source == 'workflow'``)
      3. artifact present (a deck/pdf StudioArtifact and no queryable result)
      4. dashboard (≥2 widgets, or any chart widget)
      5. result (single query result) — default

    Renderers for modes other than "result" are registered by their own phase;
    if a chosen mode has no registered renderer, the assembler falls back to
    "result", so an unbuilt phase degrades gracefully.
    """
    opt = ctx.options or {}
    fmt = (opt.get("format") or opt.get("mode") or "").lower()
    if fmt in ("dashboard", "artifact", "workflow", "result", "table"):
        return "result" if fmt == "table" else fmt
    if opt.get("source") == "workflow":
        return "workflow"

    # DB sniff — never raise into the send path.
    try:
        from sqlalchemy import select, func
        from app.dependencies import async_session_maker
        from app.models.widget import Widget
        from app.models.step import Step

        async with async_session_maker() as db:
            wids = [
                w.id for w in (
                    await db.execute(select(Widget).where(Widget.report_id == ctx.report_id))
                ).scalars().all()
            ]
            n_widgets = len(wids)
            n_charts = 0
            has_data = False
            if wids:
                steps = (
                    await db.execute(select(Step).where(Step.widget_id.in_(wids)))
                ).scalars().all()
                for s in steps:
                    if (s.type or "").lower() == "chart":
                        n_charts += 1
                    if s.data:
                        has_data = True
            # artifact detection (deck/pdf) — the FILE-bearing model is ``Artifact``
            # (table ``artifacts``: report_id + mode page/slides + pptx_path), NOT
            # StudioArtifact (which is text-only, no report_id).
            has_artifact = False
            try:
                from app.models.artifact import Artifact  # type: ignore
                cnt = (
                    await db.execute(
                        select(func.count()).select_from(Artifact).where(
                            Artifact.report_id == ctx.report_id
                        )
                    )
                ).scalar() or 0
                has_artifact = cnt > 0
            except Exception:  # noqa: BLE001 — model name/shape may differ
                has_artifact = False

        if has_artifact and not has_data:
            return "artifact"
        # A dashboard = a multi-widget report. A single widget (even a chart) is
        # still Mode A — the table renderer shows its data fine; one chart alone
        # doesn't warrant the heavier Playwright snapshot path. n_charts is kept
        # for renderers that want it but no longer triggers dashboard on its own.
        if n_widgets >= 2:
            return "dashboard"
        _ = n_charts  # informational
    except Exception:  # noqa: BLE001
        return "result"
    return "result"
