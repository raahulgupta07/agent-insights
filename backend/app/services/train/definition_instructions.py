"""Pipeline v1 (P7): publish approved Definitions as agent Instructions.

Instead of a new context builder (which would touch agent_v2/context_hub — core
files, rebase tax), approved Definitions are mirrored into the EXISTING
Instruction table. Dash already injects published instructions into every
answer, so the agent automatically applies "Lead = …", "always Status=Completed"
on ad-hoc questions — not just on saved goldens.

Idempotent + fail-soft. One Instruction per definition, keyed by a marker in
``structured_data`` so re-sync updates in place rather than duplicating.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from sqlalchemy import select, text

logger = logging.getLogger(__name__)


def _instruction_text(d) -> str:
    pred = (d.sql_predicate or "").strip()
    exp = ""
    try:
        if d.expected:
            exp = f" Verified total = {d.expected[0]['value']}."
    except Exception:  # noqa: BLE001
        pass
    return (
        f"DEFINITION — \"{d.name}\": rows WHERE {pred}.{exp} "
        f"Apply this exact predicate whenever the question asks for {d.name}. "
        f"Always filter Status='Completed' for call metrics."
    )


async def sync_definitions_to_instructions(
    db, *, organization, data_source_id: Optional[str] = None,
) -> dict:
    """Mirror every APPROVED definition into a published Instruction. Returns
    {"published": n}. Never raises."""
    from app.models.agent_definition import AgentDefinition
    from app.models.instruction import Instruction

    out = {"published": 0}
    try:
        org_id = str(organization.id)
        defs = (
            await db.execute(
                select(AgentDefinition).where(
                    AgentDefinition.organization_id == org_id,
                    AgentDefinition.status == "approved",
                    AgentDefinition.deleted_at.is_(None),
                )
            )
        ).scalars().all()

        for d in defs:
            marker = f"def:{d.id}"
            # find an existing instruction for this definition (marker in structured_data)
            existing = (
                await db.execute(
                    select(Instruction).where(
                        Instruction.organization_id == org_id,
                        Instruction.ai_source == "definition_registry",
                        Instruction.category == "definition",
                    )
                )
            ).scalars().all()
            match = None
            for ins in existing:
                sd = ins.structured_data or {}
                if isinstance(sd, dict) and sd.get("definition_marker") == marker:
                    match = ins
                    break

            body = _instruction_text(d)
            if match is None:
                ins = Instruction(
                    id=str(uuid.uuid4()), text=body, source_type="ai",
                    status="published", load_mode="always", category="definition",
                    ai_source="definition_registry", organization_id=org_id,
                    structured_data={"definition_marker": marker, "name": d.name},
                )
                db.add(ins)
                await db.flush()
                if data_source_id:
                    try:
                        await db.execute(
                            text("INSERT INTO instruction_data_source_association "
                                 "(instruction_id, data_source_id) VALUES (:i, :d) "
                                 "ON CONFLICT DO NOTHING"),
                            {"i": ins.id, "d": str(data_source_id)},
                        )
                    except Exception:  # noqa: BLE001
                        pass
            else:
                match.text = body
                match.status = "published"
            out["published"] += 1

        await db.commit()
        logger.info("definition_instructions: published %d definition(s)", out["published"])
    except Exception:  # noqa: BLE001
        logger.warning("definition_instructions.sync failed", exc_info=True)
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            pass
    return out
