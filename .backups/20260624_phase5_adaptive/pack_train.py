"""Phase 4 — Pack train wiring.

Three fail-soft, flag-gated jobs, each reusing existing services. Called from
``train_orchestrator.run_training`` as one extra stage. NEVER raises into the
orchestrator. ASCII only.

  1. autobind_library_packs  — at train time try EVERY shipped library pack
     against the studio's REAL columns (the binder). A pack whose required inputs
     all bind gets a ``pending`` StudioBoundPack row (review gate, source='pack');
     a partially-matching pack (>=1 input matched but a required one missing) gets
     a ``dormant`` row carrying its ``missing`` inputs, so the UI can say
     "needs a Budget column". Totally-irrelevant packs (0 inputs matched) are
     skipped (no clutter). Existing rows for (studio,pack_id) are NEVER touched
     (idempotent; never clobbers a human's pending/active/rejected decision).
     Gated by ``flags.PACK_AUTOBIND``.

  2. build_skill_context     — render the studio's ACTIVE bound packs (library +
     user/Teach) into a short text block (method + trigger hints + binding). The
     orchestrator feeds it into the existing auto_queries / auto_evals generators
     so the seeded examples cover the skills' computations ("seed from method").

  3. materialize_pack_goldens — turn any ``eval_goldens`` a bound pack carries
     into TestCase rows in the studio goldens suite (the same FieldRule shape
     ``auto_evals`` uses), so retrains regression-check the skill. Library packs
     ship with ``eval_goldens: []`` today, so this is a harmless no-op until a
     snapshot pass (deferred) fills them — the wiring is here so it lights up the
     moment goldens exist.

NOTE (deferred): generatively SNAPSHOTTING a pack's method on the studio's real
data to MINT new goldens (run the method -> capture headline value) needs the
full agent loop and is intentionally left for a later pass. Phase 4 instead
biases the existing cheap schema-grounded generators with skill context (job 2)
and materialises any goldens a pack already carries (job 3).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.settings.logging_config import get_logger

logger = get_logger(__name__)

# Cap how many library packs we evaluate / how much context we render (cheap tier).
_MAX_CONTEXT_PACKS = 8
_METHOD_SNIPPET = 600
_CONTEXT_CAP = 3500


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

async def _existing_pack_ids(db, studio_id: str) -> set:
    """pack_ids already bound (any status) for this studio — never re-touch."""
    from sqlalchemy import select
    from app.models.studio import StudioBoundPack

    rows = (
        await db.execute(
            select(StudioBoundPack.pack_id).where(
                StudioBoundPack.studio_id == str(studio_id),
                StudioBoundPack.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    return {str(p) for p in rows}


async def _active_packs(db, studio_id: str) -> List[dict]:
    """Resolve the studio's ACTIVE bound packs into full pack dicts + binding.

    Library rows reconstruct from the yaml registry; user/Teach rows from the
    inline ``pack_body``. Returns [{pack, binding, conf}]. Never raises -> []."""
    try:
        from sqlalchemy import select
        from app.models.studio import StudioBoundPack
        from app.ai.packs import registry

        rows = (
            await db.execute(
                select(StudioBoundPack).where(
                    StudioBoundPack.studio_id == str(studio_id),
                    StudioBoundPack.status == "active",
                    StudioBoundPack.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        out: List[dict] = []
        for r in rows:
            pack = registry.get_pack(r.pack_id)
            if not pack and isinstance(getattr(r, "pack_body", None), dict) and r.pack_body:
                pack = r.pack_body
            if not pack:
                continue
            out.append({
                "pack": pack,
                "binding": dict(r.binding_map or {}),
                "conf": float(r.conf or 0.0),
                "eval_goldens": list(getattr(r, "eval_goldens", None) or pack.get("eval_goldens") or []),
            })
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("pack_train._active_packs failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# 1. autobind every library pack at train time
# ---------------------------------------------------------------------------

async def _org_packs(db, organization) -> Dict[str, dict]:
    """Org-shared packs (Phase 5 promote-to-org) as {pack_id: (pack_body, is_org)}.
    DB-backed, writable extension of the yaml library. Never raises -> {}."""
    out: Dict[str, dict] = {}
    try:
        org_id = str(getattr(organization, "id", None) or "") if organization else ""
        if not org_id:
            return out
        from sqlalchemy import select
        from app.models.studio import OrgPack

        rows = (
            await db.execute(
                select(OrgPack).where(
                    OrgPack.organization_id == org_id,
                    OrgPack.status == "active",
                    OrgPack.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        for r in rows:
            if isinstance(r.pack_body, dict) and r.pack_body:
                out[str(r.pack_id)] = r.pack_body
    except Exception as e:  # noqa: BLE001
        logger.warning("pack_train._org_packs failed: %s", e)
    return out


async def autobind_library_packs(db, studio_id: str, organization=None) -> dict:
    """Try every library pack AND every org-shared pack against the studio's
    columns; write pending/dormant rows for those that (fully/partially) match.
    Gated by PACK_AUTOBIND.

    Returns {disabled?|bound, dormant:[{pack_id,name,missing}], skipped, existing}.
    Commits once. NEVER raises."""
    summary = {"bound": 0, "dormant": [], "skipped": 0, "existing": 0}
    try:
        from app.settings.hybrid_flags import flags

        if not getattr(flags, "PACK_AUTOBIND", False):
            return {"disabled": True, **summary}

        from app.ai.packs import registry, binder
        from app.ai.packs.teach import studio_columns
        from app.models.studio import StudioBoundPack

        library = dict(registry.all_packs())       # {pack_id: pack}  (source='pack', no body)
        org_packs = await _org_packs(db, organization)  # {pack_id: body} (source='org', inline body)
        if not library and not org_packs:
            return {"ok": True, **summary}

        existing = await _existing_pack_ids(db, studio_id)
        cols = binder.columns_from_profile(await studio_columns(db, studio_id))
        if not cols:
            return {"ok": True, "note": "no profiled columns", **summary}

        # Build the candidate set: library packs (file-backed) + org packs (inline).
        candidates = []
        for pid, pack in library.items():
            candidates.append((str(pid), pack, "pack", None))
        for pid, body in org_packs.items():
            if str(pid) in library:
                continue  # a promoted pack that shadows a library id — library wins
            candidates.append((str(pid), body, "org", body))

        wrote = 0
        for pack_id, pack, src, body in candidates:
            if pack_id in existing:
                summary["existing"] += 1
                continue
            res = binder.bind_pack(pack, cols)
            binding = res.get("binding") or {}
            bound = bool(res.get("bound"))
            missing = res.get("missing") or []
            if not bound and not binding:
                # nothing matched at all -> irrelevant pack, don't clutter
                summary["skipped"] += 1
                continue
            status = "pending" if bound else "dormant"
            db.add(StudioBoundPack(
                studio_id=str(studio_id),
                pack_id=pack_id,
                binding_map=binding,
                output_spec=pack.get("output_spec") or {},
                eval_goldens=list(pack.get("eval_goldens") or []),
                status=status,
                source=src,
                conf=res.get("overall_conf") or 0.0,
                missing=missing,
                pack_body=body,  # inline for org packs; None for file-backed library
            ))
            wrote += 1
            if bound:
                summary["bound"] += 1
            else:
                summary["dormant"].append({
                    "pack_id": pack_id,
                    "name": pack.get("name") or pack_id,
                    "missing": missing,
                })
        if wrote:
            await db.commit()
        return {"ok": True, **summary}
    except Exception as e:  # noqa: BLE001
        logger.warning("autobind_library_packs failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return {"ok": False, "error": str(e), **summary}


# ---------------------------------------------------------------------------
# 1b. re-check EXISTING bindings against the current schema (drift handler)
# ---------------------------------------------------------------------------

async def recheck_bindings(db, studio_id: str) -> dict:
    """Re-bind the studio's EXISTING pack rows against the current columns, so a
    schema change flips status the right way (Phase 5 drift handler):

      * dormant -> pending : a previously-missing required input now has a column
        (surface it for approval). Never auto-activates (review gate preserved).
      * active/pending -> dormant : a column a binding depended on disappeared
        (a required input no longer binds) — bench the pack so the router stops
        picking a method whose data is gone.

    `rejected` rows are left alone (a human said no). Gated by DOMAIN_PACKS.
    Commits once. Returns a summary. NEVER raises."""
    summary = {"revived": [], "benched": [], "rebound": 0, "checked": 0}
    try:
        from app.settings.hybrid_flags import flags
        if not getattr(flags, "DOMAIN_PACKS", False):
            return {"disabled": True, **summary}

        from sqlalchemy import select
        from app.ai.packs import registry, binder
        from app.ai.packs.teach import studio_columns
        from app.models.studio import StudioBoundPack

        rows = (
            await db.execute(
                select(StudioBoundPack).where(
                    StudioBoundPack.studio_id == str(studio_id),
                    StudioBoundPack.status.in_(["dormant", "active", "pending"]),
                    StudioBoundPack.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        if not rows:
            return {"ok": True, **summary}

        cols = binder.columns_from_profile(await studio_columns(db, studio_id))
        if not cols:
            return {"ok": True, "note": "no profiled columns", **summary}

        changed = 0
        for r in rows:
            pack = registry.get_pack(r.pack_id)
            if not pack and isinstance(getattr(r, "pack_body", None), dict) and r.pack_body:
                pack = r.pack_body
            if not pack:
                continue
            summary["checked"] += 1
            res = binder.bind_pack(pack, cols)
            bound = bool(res.get("bound"))
            new_binding = res.get("binding") or {}
            new_missing = res.get("missing") or []
            # refresh the binding snapshot + conf either way
            r.binding_map = new_binding
            r.conf = res.get("overall_conf") or 0.0
            r.missing = new_missing
            summary["rebound"] += 1
            if r.status == "dormant" and bound:
                r.status = "pending"  # re-surface for human approval
                summary["revived"].append({"pack_id": r.pack_id, "name": pack.get("name") or r.pack_id})
                changed += 1
            elif r.status in ("active", "pending") and not bound:
                r.status = "dormant"
                summary["benched"].append({"pack_id": r.pack_id, "name": pack.get("name") or r.pack_id, "missing": new_missing})
                changed += 1
        await db.commit()
        return {"ok": True, **summary}
    except Exception as e:  # noqa: BLE001
        logger.warning("recheck_bindings failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return {"ok": False, "error": str(e), **summary}


# ---------------------------------------------------------------------------
# 2. render active packs into generator context
# ---------------------------------------------------------------------------

async def build_skill_context(db, studio_id: str) -> str:
    """Short text block describing the studio's ACTIVE skills, for biasing the
    schema-grounded query / eval generators toward the skills' computations.
    Returns "" when there are no active packs. Never raises."""
    try:
        packs = await _active_packs(db, studio_id)
        if not packs:
            return ""
        lines: List[str] = [
            "ACTIVE SKILLS for this studio (prefer example queries/tests that "
            "exercise these computations on the columns shown):"
        ]
        for c in packs[:_MAX_CONTEXT_PACKS]:
            pack = c["pack"]
            name = pack.get("name") or pack.get("id") or "skill"
            method = (pack.get("method_text") or "").strip().replace("\n", " ")
            if len(method) > _METHOD_SNIPPET:
                method = method[:_METHOD_SNIPPET] + " ..."
            hints = ", ".join(str(h) for h in (pack.get("trigger_hints") or [])[:6])
            binding = c.get("binding") or {}
            bmap = ", ".join(f"{k}=\"{v}\"" for k, v in list(binding.items())[:12])
            lines.append(f"- {name}")
            if method:
                lines.append(f"    method: {method}")
            if hints:
                lines.append(f"    asked as: {hints}")
            if bmap:
                lines.append(f"    columns: {bmap}")
        text = "\n".join(lines)
        return text[:_CONTEXT_CAP]
    except Exception as e:  # noqa: BLE001
        logger.warning("build_skill_context failed: %s", e)
        return ""


# ---------------------------------------------------------------------------
# 3. materialise pack-carried goldens into the studio goldens suite
# ---------------------------------------------------------------------------

def _golden_pair(g: Any) -> Optional[tuple]:
    """Tolerant (question, expected) extraction from one pack golden. -> None."""
    if not isinstance(g, dict):
        return None
    q = g.get("question") or g.get("prompt") or g.get("q")
    exp = g.get("expect") or g.get("expected") or g.get("value") or g.get("contains")
    q = str(q).strip() if q is not None else ""
    exp = str(exp).strip() if exp is not None else ""
    if q and exp:
        return q[:120], exp[:80]
    return None


async def materialize_pack_goldens(db, organization, studio_id: str) -> dict:
    """Create TestCase rows from any eval_goldens the studio's ACTIVE packs carry.

    Reuses the exact suite + FieldRule shape ``auto_evals`` uses (a FLAT matcher
    is silently skipped -> vacuous pass; must be a FieldRule). Dedupe by
    (suite, name). Born active (explicit goldens). Never raises."""
    created = 0
    skipped = 0
    try:
        from app.settings.hybrid_flags import flags

        if not getattr(flags, "DOMAIN_PACKS", False):
            return {"disabled": True, "created": 0}

        packs = await _active_packs(db, studio_id)
        pairs: List[tuple] = []
        for c in packs:
            for g in (c.get("eval_goldens") or []):
                pr = _golden_pair(g)
                if pr:
                    pairs.append(pr)
        if not pairs:
            return {"ok": True, "created": 0, "skipped": 0}

        from sqlalchemy import select
        from app.services.eval_harness import _find_or_create_suite
        from app.models.eval import TestCase
        from app.ai.knowledge.auto_evals import _make_field_rule, _resolve_first_pinned_source
        from app.models.studio import Studio

        org_id = str(getattr(organization, "id", None) or "")
        if not org_id:
            return {"ok": False, "error": "no organization", "created": 0}

        suite = await _find_or_create_suite(
            db, org_id=org_id, name=f"Studio {studio_id} goldens"
        )
        if suite is None:
            return {"ok": False, "error": "could not create suite", "created": 0}
        suite_id = str(suite.id)

        # Resolve a source id for the case (best-effort; goldens still valid without).
        source_ids: List[str] = []
        try:
            studio = (
                await db.execute(select(Studio).where(Studio.id == studio_id))
            ).scalar_one_or_none()
            if studio is not None:
                ds = await _resolve_first_pinned_source(db, studio, organization)
                if ds is not None:
                    source_ids = [str(ds.id)]
        except Exception:
            source_ids = []

        for question, expected in pairs:
            name = question
            exists = (
                await db.execute(
                    select(TestCase.id)
                    .where(TestCase.suite_id == suite_id)
                    .where(TestCase.name == name)
                    .limit(1)
                )
            ).first()
            if exists is not None:
                skipped += 1
                continue
            db.add(TestCase(
                suite_id=suite_id,
                name=name,
                prompt_json={"content": question, "mode": "default"},
                expectations_json={
                    "spec_version": 1,
                    "rules": [_make_field_rule(expected)],
                    "order_mode": "flexible",
                },
                data_source_ids_json=source_ids,
                status="active",
                auto_generated=True,
            ))
            created += 1
        if created:
            await db.commit()
        return {"ok": True, "created": created, "skipped": skipped, "suite_id": suite_id}
    except Exception as e:  # noqa: BLE001
        logger.warning("materialize_pack_goldens failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
        return {"ok": False, "error": str(e), "created": created}
