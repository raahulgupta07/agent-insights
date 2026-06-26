"""Playwright snapshot helpers for the dashboard report-delivery renderer.

A "dashboard" email carries an inline hero PNG (rendered in the body) and an
attached PDF of the same multi-widget report. Both come from rendering the
report's HTML once in a single headless-Chromium page — this module opens ONE
browser/page, sets the report HTML, then takes a full-page screenshot AND a PDF
from that same page (cheaper than two launches).

The report HTML is built the same way ``report_pdf_service`` builds it:
  * if the report has a rendered artifact, reuse that artifact's HTML (the rich
    React dashboard, identical to the in-app render); otherwise
  * build a simple, robust HTML from the report's widgets/steps — each widget's
    title + its latest step's data table (via ``template.table_html``).

Everything here is fail-soft: any failure (Playwright missing, no HTML, render
error) returns ``(None, None)`` so the renderer can fall back gracefully and
never raise into the send path.
"""
from __future__ import annotations

import asyncio
import html as _h
import json
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


async def dashboard_snapshot(report_id: str) -> Tuple[Optional[bytes], Optional[bytes]]:
    """Render a report to ``(png_bytes, pdf_bytes)`` via one Playwright page.

    Returns ``(None, None)`` on any failure (no HTML, Playwright unavailable,
    render error) — never raises.
    """
    try:
        html_content = await _build_report_html(report_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("dashboard_snapshot: HTML build failed for %s: %s", report_id, e)
        return None, None
    if not html_content:
        logger.info("dashboard_snapshot: no renderable HTML for report %s", report_id)
        return None, None

    return await _render_png_and_pdf(html_content, report_id)


# ---- single-browser render (png + pdf from one page) ----------------------

async def _render_png_and_pdf(
    html_content: str, label: str
) -> Tuple[Optional[bytes], Optional[bytes]]:
    """Open one browser/page, set the HTML, return (png_bytes, pdf_bytes).

    Mirrors ``report_pdf_service``'s exact launch + wait sequence so artifact
    dashboards (React) get time to mount before we capture both outputs.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("dashboard_snapshot: Playwright not installed")
        return None, None

    png_bytes: Optional[bytes] = None
    pdf_bytes: Optional[bytes] = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page(viewport={"width": 1280, "height": 720})
                await page.set_content(html_content, wait_until="networkidle")

                # Wait for React to mount (artifact dashboards). No-op for the
                # simple table HTML (no #root spinners) — guarded, never fatal.
                try:
                    await page.wait_for_function(
                        """
                        () => {
                            const root = document.getElementById('root');
                            if (!root) return true;
                            if (root.children.length === 0) return false;
                            const spinners = root.querySelectorAll('svg animateTransform');
                            for (let i = 0; i < spinners.length; i++) {
                                const svg = spinners[i].closest('svg');
                                if (svg && svg.offsetWidth > 0 && svg.offsetHeight > 0) return false;
                            }
                            return true;
                        }
                        """,
                        timeout=15000,
                    )
                except Exception:
                    pass

                # Wait for charts/tables/text to render.
                try:
                    await page.wait_for_function(
                        """
                        () => {
                            const root = document.getElementById('root') || document.body;
                            if (!root) return false;
                            const hasContent = root.querySelectorAll('canvas, svg:not([class*="spinner"]):not([class*="loading"]), table, .recharts-wrapper, [class*="chart"], [class*="viz"]').length > 0;
                            const hasText = root.innerText && root.innerText.trim().length > 20;
                            return hasContent || hasText;
                        }
                        """,
                        timeout=30000,
                    )
                except Exception:
                    logger.warning("dashboard_snapshot: timed out waiting for content (%s)", label)

                # Let chart animations settle.
                await asyncio.sleep(3)

                # Capture BOTH from the same loaded page.
                try:
                    png_bytes = await page.screenshot(full_page=True, type="png")
                except Exception as e:  # noqa: BLE001
                    logger.warning("dashboard_snapshot: screenshot failed (%s): %s", label, e)
                try:
                    pdf_bytes = await page.pdf(
                        format="A4",
                        print_background=True,
                        margin={"top": "0.5in", "bottom": "0.5in", "left": "0.5in", "right": "0.5in"},
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning("dashboard_snapshot: pdf failed (%s): %s", label, e)
            finally:
                await browser.close()
    except Exception as e:  # noqa: BLE001
        logger.warning("dashboard_snapshot: Playwright render failed (%s): %s", label, e)
        return None, None

    return (png_bytes or None), (pdf_bytes or None)


# ---- report HTML build (artifact reuse, else widgets/steps) ---------------

async def _build_report_html(report_id: str) -> Optional[str]:
    """Build the report's renderable HTML.

    Prefer the report's latest rendered artifact (the rich in-app dashboard);
    otherwise build a simple HTML from widgets/steps. Read-only.
    """
    from sqlalchemy import select, desc
    from app.dependencies import async_session_maker
    from app.models.report import Report
    from app.models.widget import Widget
    from app.models.step import Step

    async with async_session_maker() as db:
        report = await db.get(Report, report_id)
        if not report:
            return None

        # 1) Prefer a rendered artifact — reuse report_pdf_service's exact path.
        artifact_html = await _artifact_html(db, report_id)
        if artifact_html:
            return artifact_html

        # 2) Fallback: simple HTML from widgets + each widget's latest step data.
        widgets = (
            await db.execute(
                select(Widget).where(Widget.report_id == report_id).order_by(Widget.y, Widget.x)
            )
        ).scalars().all()
        if not widgets:
            return None

        from app.services.report_delivery import template
        try:
            from app.services.parquet_store import hydrate as _hydrate
        except Exception:  # noqa: BLE001
            _hydrate = lambda d: d  # noqa: E731

        sections: list[str] = []
        for w in widgets:
            steps = (
                await db.execute(
                    select(Step)
                    .where(Step.widget_id == w.id)
                    .order_by(desc(Step.created_at))
                    .limit(8)
                )
            ).scalars().all()
            step = next((s for s in steps if s.data), None)
            table = ""
            if step is not None and step.data:
                try:
                    sd = _hydrate(step.data)
                except Exception:  # noqa: BLE001
                    sd = step.data
                result = _result_from_step_data(sd)
                if result:
                    table = template.table_html(result, max_rows=25)
            wtitle = (w.title or (step.title if step else "") or "Widget").strip()
            sections.append(
                "<section style='margin:0 0 28px'>"
                f"<h3 style='font:600 16px Segoe UI,Arial,sans-serif;color:#211B14;margin:0 0 8px'>"
                f"{_h.escape(wtitle)}</h3>"
                f"{table or '<p style=\"color:#9a958c;font:13px Segoe UI,Arial,sans-serif\">No data</p>'}"
                "</section>"
            )

        title = (report.title or "Dashboard").strip()
        body = "".join(sections)
        return (
            "<!DOCTYPE html><html><head><meta charset='UTF-8'>"
            "<style>html,body{margin:0;padding:0;background:#fff}"
            "body{padding:28px 32px;font-family:Segoe UI,Arial,sans-serif;color:#222}</style>"
            "</head><body>"
            f"<h1 style='font:600 24px Segoe UI,Arial,sans-serif;color:#211B14;margin:0 0 20px'>"
            f"{_h.escape(title)}</h1>"
            f"{body}"
            "</body></html>"
        )


async def _artifact_html(db, report_id: str) -> Optional[str]:
    """Build HTML for the report's latest artifact, reusing report_pdf_service's
    builder (visualization hydration + inline artifact scripts). None if no
    usable artifact or the path is unavailable."""
    try:
        from sqlalchemy import select, desc
        from app.models.artifact import Artifact
        from app.models.report import Report
        from app.models.visualization import Visualization
        from app.models.query import Query
        from app.models.step import Step
        from sqlalchemy.orm import selectinload
        from app.services.report_pdf_service import ReportPdfService
    except Exception as e:  # noqa: BLE001
        logger.info("dashboard_snapshot: artifact path unavailable: %s", e)
        return None

    artifact = (
        await db.execute(
            select(Artifact)
            .where(Artifact.report_id == report_id, Artifact.deleted_at.is_(None))
            .order_by(desc(Artifact.created_at))
            .limit(1)
        )
    ).scalar_one_or_none()
    if not artifact or not artifact.content:
        return None

    report = await db.get(Report, report_id)
    if not report:
        return None

    viz_stmt = (
        select(Visualization)
        .options(selectinload(Visualization.query))
        .where(Visualization.report_id == report_id)
    )
    visualizations = (await db.execute(viz_stmt)).scalars().all()

    from app.services.parquet_store import hydrate as _hydrate_parquet

    viz_data = []
    for viz in visualizations:
        if not viz.query_id:
            continue
        query = await db.get(Query, viz.query_id)
        if not query:
            continue
        step = None
        if query.default_step_id:
            step = await db.get(Step, query.default_step_id)
        if not step:
            step = (
                await db.execute(
                    select(Step).where(Step.query_id == query.id)
                    .order_by(desc(Step.created_at)).limit(1)
                )
            ).scalar_one_or_none()
        _sd = _hydrate_parquet(step.data) if step and step.data else {}
        viz_data.append({
            "id": str(viz.id),
            "title": viz.title or query.title or "Untitled",
            "view": viz.view or {},
            "rows": _sd.get("rows", []) if isinstance(_sd, dict) else [],
            "columns": _sd.get("columns", []) if isinstance(_sd, dict) else [],
            "dataModel": (step.data_model or {}) if step else {},
        })

    artifact_code = artifact.content.get("code", "") if isinstance(artifact.content, dict) else ""
    if not artifact_code:
        return None

    svc = ReportPdfService()
    return svc._build_pdf_html(
        report_id=str(report.id),
        report_title=report.title,
        report_theme=getattr(report, "theme_name", None),
        artifact_code=artifact_code,
        visualizations=viz_data,
        mode=getattr(artifact, "mode", None) or "page",
    )


def _result_from_step_data(data) -> Optional[dict]:
    """Coerce a step's ``data`` into ``{columns, rows}`` for template.table_html."""
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:  # noqa: BLE001
            return None
    rows = cols = None
    if isinstance(data, dict):
        cols = data.get("columns") or data.get("schema")
        rows = data.get("rows") or data.get("data")
        if isinstance(cols, list) and cols and isinstance(cols[0], dict):
            cols = [c.get("field") or c.get("name") or c.get("headerName") for c in cols]
    elif isinstance(data, list):
        rows = data
        if rows and isinstance(rows[0], dict):
            cols = list(rows[0].keys())
    if not rows:
        return None
    if not cols and isinstance(rows[0], dict):
        cols = list(rows[0].keys())
    return {"columns": cols or [], "rows": rows}
