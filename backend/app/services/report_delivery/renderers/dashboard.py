"""Mode B — dashboard renderer.

A multi-widget report is delivered as an inline hero PNG (rendered in the email
body) plus an attached PDF of the same report, alongside a short sanitized intro
and key-insight bullets pulled from the agent's narrative.

Registers itself as the ``"dashboard"`` mode on import (see ``renderers/__init__``
for auto-discovery). Fail-soft: if the Playwright snapshot is unavailable (missing
dep / render error / no HTML) the renderer still returns a valid text-only email
with a short note — it never raises into the send path.
"""
from __future__ import annotations

import logging

from app.services.report_delivery.contract import (
    Attachment,
    DeliveryContext,
    DeliveryParts,
    InlineImage,
    register_renderer,
)
from app.services.report_delivery import render_service, template
from app.services.report_delivery.extract import (
    latest_narrative,
    sanitize_chat_content,
    split_intro_and_insights,
)

logger = logging.getLogger(__name__)

_META = "Automated dashboard · agent report"
_FOOTER = "Generated automatically and delivered via this agent's email."


def _intro_html(intro: str) -> str:
    if not intro:
        return ""
    return f"<p style='margin:0 0 16px;font-size:14px;line-height:1.55'>{intro}</p>"


async def render(ctx: DeliveryContext) -> DeliveryParts:
    title = ctx.title or "Dashboard"

    # 1) sanitized intro + insight bullets from the agent's narrative.
    try:
        narrative = sanitize_chat_content(await latest_narrative(ctx.report_id))
    except Exception as e:  # noqa: BLE001 — never block the send path
        logger.warning("dashboard renderer: narrative fetch failed for %s: %s", ctx.report_id, e)
        narrative = ""
    intro, insights = split_intro_and_insights(narrative)

    # 2) one-pass Playwright snapshot → (png, pdf). Fail-soft to (None, None).
    try:
        png_bytes, pdf_bytes = await render_service.dashboard_snapshot(ctx.report_id)
    except Exception as e:  # noqa: BLE001
        logger.warning("dashboard renderer: snapshot raised for %s: %s", ctx.report_id, e)
        png_bytes = pdf_bytes = None

    # 5) FAIL-SOFT: no image → text-only email with a note, no inline/attachment.
    if not png_bytes:
        note = (
            "<p style='margin:0 0 16px;font-size:13px;color:#9a958c'>"
            "Dashboard image unavailable — open the report to view the full dashboard.</p>"
        )
        inner = _intro_html(intro) + note + template.insights_html(insights)
        body = template.skeleton(
            title=title, meta=_META, inner_html=inner,
            report_url=ctx.report_url, footer=_FOOTER,
        )
        return DeliveryParts(body_html=body, subject=title)

    # 3) intro + inline hero image + insights.
    img = (
        "<img src=\"cid:dashboard\" alt=\"Dashboard\" "
        "style=\"max-width:600px;width:100%;border:1px solid #eee;border-radius:8px;"
        "margin:4px 0 8px\">"
    )
    inner = _intro_html(intro) + img + template.insights_html(insights)
    body = template.skeleton(
        title=title, meta=_META, inner_html=inner,
        report_url=ctx.report_url, footer=_FOOTER,
    )

    # 4) inline PNG (always) + attached PDF (when available).
    attachments = []
    if pdf_bytes:
        attachments.append(
            Attachment(f"{title}.pdf", pdf_bytes, "application", "pdf")
        )
    return DeliveryParts(
        body_html=body,
        inline_images=[InlineImage("dashboard", png_bytes, "png")],
        attachments=attachments,
        subject=title,
    )


register_renderer("dashboard", render)
