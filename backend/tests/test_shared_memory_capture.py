"""Unit tests — Shared Memory capture: pure gate/hash + DB singularize (P2).

Pure parts run anywhere. The DB part uses async in-memory SQLite (the model is
plain columns + JSON, SQLite-compatible) to prove the singularize upsert:
re-capturing the same fact bumps verified_count and promotes at >=2, instead of
inserting duplicates.

Run: python -m pytest backend/tests/test_shared_memory_capture.py -q
"""
import asyncio

from app.services.knowledge import capture as C


# --- pure: confidence gate + dedupe hash -----------------------------------

def test_status_gate():
    assert C.status_for(is_private=True, verified=False, count=1) == "active"   # private trusted now
    assert C.status_for(is_private=False, verified=False, count=1) == "pending" # shared, 1st sight
    assert C.status_for(is_private=False, verified=False, count=2) == "active"  # 2nd confirm -> promote
    assert C.status_for(is_private=False, verified=True, count=1) == "active"   # explicit verified


def test_content_hash_stable_and_order_insensitive():
    a = C.content_hash("mistake", {"x": 1, "y": 2})
    b = C.content_hash("mistake", {"y": 2, "x": 1})
    c = C.content_hash("mistake", {"x": 1, "y": 3})
    assert a == b and a != c


def test_prep_share_blocks_data_in_shared_keeps_private():
    payload = {"table": "projects", "rows": [{"n": 258}]}
    ok_shared, clean = C.prep_share(payload, is_private=False)
    assert ok_shared and "rows" not in clean and "258" not in str(clean)
    ok_priv, raw = C.prep_share(payload, is_private=True)
    assert ok_priv and raw == payload  # private kept raw


# --- DB: singularize upsert -------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


async def _mk_session():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.models.base import Base
    from app.models.agent_knowledge import AgentKnowledge  # noqa: F401 (register)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: AgentKnowledge.__table__.create(c))
    return async_sessionmaker(engine, expire_on_commit=False)()


def test_singularize_upsert_and_promote():
    async def go():
        from sqlalchemy import select
        from app.models.agent_knowledge import AgentKnowledge

        db = await _mk_session()
        scope = [{"scope_kind": "model", "scope_key": "ad16d612"}]
        content = {"kind": "query_template", "template": "EVALUATE TOPN({value}, projects)"}

        # 1st capture (unverified) -> pending, count 1
        n = await C.capture(db, organization_id="org1", scopes=scope,
                            kind="query_template", title="t", content=content)
        await db.commit()
        rows = (await db.execute(select(AgentKnowledge))).scalars().all()
        assert n == 1 and len(rows) == 1
        assert rows[0].verified_count == 1 and rows[0].status == "pending"

        # 2nd capture of the SAME fact -> singularized (still 1 row), count 2, promoted
        await C.capture(db, organization_id="org1", scopes=scope,
                        kind="query_template", title="t", content=content)
        await db.commit()
        rows = (await db.execute(select(AgentKnowledge))).scalars().all()
        assert len(rows) == 1, "must dedupe, not insert a duplicate"
        assert rows[0].verified_count == 2 and rows[0].status == "active"

        # a DIFFERENT scope key -> separate row (isolation preserved)
        await C.capture(db, organization_id="org1",
                        scopes=[{"scope_kind": "model", "scope_key": "other"}],
                        kind="query_template", title="t", content=content)
        await db.commit()
        rows = (await db.execute(select(AgentKnowledge))).scalars().all()
        assert len(rows) == 2

    _run(go())


def test_private_scope_active_immediately():
    async def go():
        from sqlalchemy import select
        from app.models.agent_knowledge import AgentKnowledge
        db = await _mk_session()
        await C.capture(db, organization_id="org1",
                        scopes=[{"scope_kind": "user", "scope_key": "u1"}],
                        kind="howto", title="mine", content={"how": "did X"},
                        user_id="u1")
        await db.commit()
        row = (await db.execute(select(AgentKnowledge))).scalars().one()
        assert row.scope_kind == "user" and row.status == "active"
    _run(go())
