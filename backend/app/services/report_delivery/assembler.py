"""Orchestrator: classify a report → run the matching mode renderer → return the
email parts. Plus a thin ``deliver`` that hands the parts to the per-agent SMTP
transport (the same path channels/shares use), so the per-agent identity holds.

This is the single entry point ``notification_service`` calls when
``flags.RICH_REPORT_EMAIL`` is on. When off, the caller keeps its legacy path —
nothing here runs.
"""
from __future__ import annotations

import logging
import os
import tempfile

from app.services.report_delivery.contract import (
    DeliveryContext,
    DeliveryParts,
    classify,
    get_renderer,
)

logger = logging.getLogger(__name__)


async def build_parts(ctx: DeliveryContext) -> DeliveryParts:
    """Classify + render. Always returns a DeliveryParts (fallbacks inside the
    renderer); raises only on a truly missing renderer (shouldn't happen)."""
    # side-effect import registers all built renderers
    from app.services.report_delivery import renderers  # noqa: F401

    mode = await classify(ctx)
    renderer = get_renderer(mode) or get_renderer("result")
    if renderer is None:
        raise RuntimeError("report_delivery: no renderer registered")
    return await renderer(ctx)


def _attachments_to_send_dicts(parts: DeliveryParts) -> list[dict]:
    """Write attachment bytes to temp files in the shape ``_resolved_send`` reads
    ({file, filename, type, subtype}). Mode A has none; dashboard/artifact use it."""
    out: list[dict] = []
    for att in parts.attachments:
        try:
            fd, path = tempfile.mkstemp(suffix="_" + att.filename)
            with os.fdopen(fd, "wb") as f:
                f.write(att.content)
            out.append({
                "file": path,
                "filename": att.filename,
                "type": att.mime_type,
                "subtype": att.mime_subtype,
            })
        except Exception as e:  # noqa: BLE001
            logger.warning("report_delivery: attachment write failed (%s): %s", att.filename, e)
    return out


async def deliver(
    ctx: DeliveryContext,
    recipients: list[str],
    *,
    db,
) -> bool:
    """Build parts and send via the purpose-resolved per-agent SMTP transport.

    Routes with ``studio_id=ctx.studio_id`` so an agent's report sends from its
    own SMTP identity (per-agent override), falling back to org/global SMTP.
    """
    parts = await build_parts(ctx)
    subject = parts.subject or ctx.title or "Report"

    # Sense-Making decision lead (flag-gated, fail-soft). PREPEND a "Decision"
    # box above the rendered result and tag the subject with the action. On any
    # error the email is delivered exactly as today (no lead block). Flag OFF →
    # byte-identical to today. Reuses the already-stored card (NO LLM).
    try:
        from app.settings.hybrid_flags import flags as _sm_flags
        if getattr(_sm_flags, "SENSE_MAKING", False):
            from app.ai.knowledge.sense_maker import get_stored_sense_making
            from app.services.report_delivery import template as _tpl
            sm = await get_stored_sense_making(db, ctx.report_id)
            if sm:
                lead = _tpl.sense_making_lead_html(sm)
                if lead:
                    parts.body_html = lead + (parts.body_html or "")
                    tag = _tpl.sense_making_subject_tag(sm)
                    if tag and not subject.startswith(tag):
                        subject = tag + subject
    except Exception:  # noqa: BLE001 — deliver exactly as today on any error
        logger.warning("report_delivery: sense-making lead failed", exc_info=True)

    send_attachments = _attachments_to_send_dicts(parts) or None
    try:
        if parts.inline_images:
            # Inline (cid) images need a multipart/related message that
            # ``_resolved_send`` doesn't build — construct + send it directly via
            # the per-agent resolved SMTP, with the same transient-retry.
            return await _send_with_inline(ctx, recipients, subject, parts, send_attachments, db)
        return await _send_plain(ctx, recipients, subject, parts.body_html, send_attachments, db)
    finally:
        for d in (send_attachments or []):
            try:
                os.unlink(d["file"])
            except OSError:
                pass


async def _send_plain(ctx, recipients, subject, body_html, send_attachments, db) -> bool:
    """No inline images → reuse notification_service._resolved_send (per-agent SMTP)."""
    import asyncio
    from app.services.notification_service import notification_service

    ok = False
    for attempt in range(3):
        ok = await notification_service._resolved_send(
            recipients, subject, body_html,
            subtype="html", attachments=send_attachments,
            db=db, organization_id=ctx.organization_id,
            purpose="system", studio_id=ctx.studio_id,
        )
        if ok:
            break
        if attempt < 2:
            logger.warning("report_delivery: send attempt %d failed, retrying", attempt + 1)
            await asyncio.sleep(2 * (attempt + 1))
    return ok


async def _send_with_inline(ctx, recipients, subject, parts, send_attachments, db) -> bool:
    """Build a multipart/related message (inline cid images) and send via the
    per-agent resolved SMTP transport directly."""
    import asyncio
    from app.services.email_client_resolver import resolve_outbound
    from app.services.email.message_builder import build_email
    from app.services.email.sender import send_message

    resolved = await resolve_outbound(db, ctx.organization_id, purpose="system", studio_id=ctx.studio_id)
    if not (resolved and resolved.uses_smtp_config and resolved.smtp_config):
        # No SMTP config resolved (e.g. only a global fastapi-mail client) — fall
        # back to the plain path so the report still goes out (sans inline image).
        logger.warning("report_delivery: no SMTP config for inline send, falling back to plain")
        return await _send_plain(ctx, recipients, subject, parts.body_html, send_attachments, db)

    inline = [(im.cid, im.content, im.mime_subtype) for im in parts.inline_images]
    att_tuples = [
        (a.filename, a.content, f"{a.mime_type}/{a.mime_subtype}") for a in parts.attachments
    ]
    all_ok = True
    for rcpt in recipients:
        msg = build_email(
            from_address=resolved.from_address, from_name=resolved.from_name,
            to_address=rcpt, subject=subject, body=parts.body_html, body_subtype="html",
            attachments=att_tuples or None, inline_images=inline or None,
        )
        sent = False
        for attempt in range(3):
            sent = await send_message(resolved.smtp_config, msg)
            if sent:
                break
            if attempt < 2:
                logger.warning("report_delivery: inline send attempt %d failed, retrying", attempt + 1)
                await asyncio.sleep(2 * (attempt + 1))
        all_ok = all_ok and sent
    return all_ok
