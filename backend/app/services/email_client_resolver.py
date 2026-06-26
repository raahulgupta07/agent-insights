"""Per-organization outbound email resolution (purpose-aware).

Two kinds of outbound mail use different transports:

- **analyst** — the agent ``send_email`` tool + channel replies. Always the
  **AI mailbox** (the Email integration), so the From identity and reply
  threading hold. Falls back to org-SMTP/global only if no AI mailbox exists.
- **system** — shares, scheduled reports, verification/registration links, any
  notification. Precedence: **Org SMTP** (``OrganizationSettings.config.smtp``)
  → **Global SMTP** (``settings.email_client`` from dash-config). **Never** the
  AI mailbox.

Backward/forward compatible:
- Org with no DB SMTP → falls through to the global dash-config client.
- Org that sets DB SMTP → uses it even when the global dash-config SMTP is empty.

The decision is isolated in :func:`choose_outbound` (pure, unit-tested);
:func:`resolve_outbound` is the DB-backed wrapper.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from app.services.email.sender import SmtpConfig

logger = logging.getLogger(__name__)


@dataclass
class ResolvedOutbound:
    """How to send mail for a given org + purpose."""

    # "ai_mailbox" | "org_smtp" | "global" | "none"
    source: str
    smtp_config: Optional[SmtpConfig] = None
    from_address: Optional[str] = None
    from_name: Optional[str] = None

    @property
    def uses_smtp_config(self) -> bool:
        """True when we should send via build_email + sender (not fastapi-mail).

        ``studio_smtp`` (per-agent custom SMTP) also uses this transport — it was
        missing here, so per-agent sends via ``_resolved_send`` silently fell back
        to the global fastapi-mail client (and failed when none is configured).
        """
        return self.source in ("ai_mailbox", "org_smtp", "studio_smtp")

    @property
    def uses_global(self) -> bool:
        return self.source == "global"

    # Back-compat alias (old callers checked uses_integration).
    @property
    def uses_integration(self) -> bool:
        return self.uses_smtp_config


def _ai_mailbox_resolved(ai_config: Optional[dict], ai_creds: Optional[dict]) -> Optional[ResolvedOutbound]:
    creds = ai_creds or {}
    cfg = ai_config or {}
    host = creds.get("smtp_host") or cfg.get("smtp_host")
    if not host:
        return None
    return ResolvedOutbound(
        source="ai_mailbox",
        smtp_config=SmtpConfig.from_credentials(creds, cfg),
        from_address=(creds.get("from_address") or cfg.get("from_address") or creds.get("smtp_username")),
        from_name=cfg.get("from_name"),
    )


def _org_smtp_resolved(org_smtp: Optional[dict]) -> Optional[ResolvedOutbound]:
    if not (org_smtp and org_smtp.get("enabled") and org_smtp.get("host")):
        return None
    return ResolvedOutbound(
        source="org_smtp",
        smtp_config=SmtpConfig(
            host=org_smtp["host"],
            port=int(org_smtp.get("port") or 587),
            username=org_smtp.get("username"),
            password=org_smtp.get("password"),
            security=org_smtp.get("security") or "starttls",
            validate_certs=bool(org_smtp.get("validate_certs", True)),
        ),
        from_address=(org_smtp.get("from_address") or org_smtp.get("username")),
        from_name=org_smtp.get("from_name"),
    )


def _studio_smtp_resolved(studio_smtp: Optional[dict]) -> Optional[ResolvedOutbound]:
    """Per-agent custom SMTP (``Studio.config['smtp']`` with ``mode == 'custom'``).

    A deliberate per-agent override; when present it wins over org/global so an
    agent's outbound mail (shares, scheduled results, channel replies) sends from
    its own sender identity. ``None`` when the agent inherits the global default.
    """
    if not (studio_smtp and studio_smtp.get("host")):
        return None
    return ResolvedOutbound(
        source="studio_smtp",
        smtp_config=SmtpConfig(
            host=studio_smtp["host"],
            port=int(studio_smtp.get("port") or 587),
            username=studio_smtp.get("username"),
            password=studio_smtp.get("password"),
            security=studio_smtp.get("security") or "starttls",
            validate_certs=bool(studio_smtp.get("validate_certs", True)),
        ),
        from_address=(studio_smtp.get("from_address") or studio_smtp.get("username")),
        from_name=studio_smtp.get("from_name"),
    )


def choose_outbound(
    purpose: str,
    ai_config: Optional[dict],
    ai_creds: Optional[dict],
    org_smtp: Optional[dict],
    *,
    global_present: bool,
    studio_smtp: Optional[dict] = None,
) -> ResolvedOutbound:
    """Pure resolution. ``purpose`` is "analyst" or "system".

    Precedence: **per-agent custom SMTP** (``studio_smtp``) → AI mailbox (analyst
    only) → **Org SMTP** → **Global SMTP**. ``studio_smtp``/``org_smtp`` are
    decrypted SMTP dicts ``{enabled, host, port, security, username, password,
    from_address, from_name}`` or ``None``.
    """
    # A per-agent custom SMTP is an explicit override — it wins for either purpose.
    studio = _studio_smtp_resolved(studio_smtp)
    if studio:
        return studio

    if purpose == "analyst":
        ai = _ai_mailbox_resolved(ai_config, ai_creds)
        if ai:
            return ai
        # No AI mailbox configured — analyst mail still needs to go out, so use
        # the system precedence (org SMTP → global).

    org = _org_smtp_resolved(org_smtp)
    if org:
        return org
    return ResolvedOutbound(source="global" if global_present else "none")


async def get_org_smtp(db, organization_id: str) -> Optional[dict]:
    """Load + decrypt the org's SMTP settings from OrganizationSettings.config.smtp."""
    if not organization_id:
        return None
    from sqlalchemy import select
    from app.models.organization_settings import OrganizationSettings
    from app.services.email.secrets import decrypt_secret

    stmt = select(OrganizationSettings).where(
        OrganizationSettings.organization_id == organization_id
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if not row or not isinstance(row.config, dict):
        return None
    smtp = row.config.get("smtp")
    if not isinstance(smtp, dict):
        return None
    out = dict(smtp)
    out["password"] = decrypt_secret(smtp.get("password_enc"))
    return out


async def get_studio_smtp(db, studio_id: str) -> Optional[dict]:
    """Load + decrypt a per-agent custom SMTP from ``Studio.config['smtp']``.

    Returns the decrypted dict only when the agent opted into a custom server
    (``mode == 'custom'`` and a host is set); otherwise ``None`` so the agent
    inherits the org/global default.
    """
    if not studio_id:
        return None
    from sqlalchemy import select
    from app.models.studio import Studio
    from app.services.email.secrets import decrypt_secret

    result = await db.execute(select(Studio).where(Studio.id == studio_id))
    studio = result.scalar_one_or_none()
    if not studio or not isinstance(studio.config, dict):
        return None
    smtp = studio.config.get("smtp")
    if not isinstance(smtp, dict):
        return None
    if (smtp.get("mode") or "global") != "custom" or not smtp.get("host"):
        return None
    out = dict(smtp)
    out["password"] = decrypt_secret(smtp.get("password_enc"))
    return out


async def resolve_outbound(
    db, organization_id: str, purpose: str = "system", studio_id: Optional[str] = None
) -> ResolvedOutbound:
    """DB-backed resolution for ``organization_id`` + ``purpose``.

    When ``studio_id`` is given and that agent has a custom SMTP configured, the
    agent's server wins over org/global (per-agent override). Otherwise behaves
    exactly as before.
    """
    from sqlalchemy import select
    from app.models.external_platform import ExternalPlatform
    from app.settings.config import settings

    ai_config = ai_creds = None
    if purpose == "analyst" and organization_id:
        stmt = select(ExternalPlatform).where(
            ExternalPlatform.organization_id == organization_id,
            ExternalPlatform.platform_type == "email",
            ExternalPlatform.is_active == True,  # noqa: E712
        )
        result = await db.execute(stmt)
        platform = result.scalar_one_or_none()
        if platform:
            ai_config = platform.platform_config
            ai_creds = platform.decrypt_credentials()

    studio_smtp = await get_studio_smtp(db, studio_id) if studio_id else None
    org_smtp = await get_org_smtp(db, organization_id)
    return choose_outbound(
        purpose, ai_config, ai_creds, org_smtp,
        global_present=settings.email_client is not None,
        studio_smtp=studio_smtp,
    )
