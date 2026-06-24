"""Unit tests for the "Save as skill" authoring service.

Deterministic, no Postgres, no LLM, no app conftest. We load
``app/services/skill_authoring.py`` directly by file path (like
``test_llm_concurrency.py``) so importing the normal package tree — which would
eagerly pull SQLAlchemy models / provider clients — never fires under
``--noconftest`` on Python 3.9 (no ``X | None`` syntax; async driven via
``asyncio.run`` like ``test_distiller.py``).

For ``distill_skill_from_completion`` we ALWAYS inject ``llm_inference`` so the
lazy ``app.ai.llm`` import is skipped, and we stub the two lazy imports the
write path needs (``app.settings.hybrid_flags`` and ``app.models.skill``) via
``sys.modules`` so the module loads standalone with no real app deps.

Contract under test (``app.services.skill_authoring``):
 - build_skill_prompt is pure over (question, answer, sql); includes the SQL block
   only when sql is provided
 - parse_skill_draft: happy path -> dict; malformed -> None; too-short -> None
 - distill_skill_from_completion: flag off -> None; missing q/a -> None;
   happy path -> inserts a DRAFT PERSONAL 'authored' skill + returns its id;
   unparseable draft -> None; error -> rolled back, None
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types
from types import SimpleNamespace

import pytest


# --------------------------------------------------------------------------- #
# Load the service module by path, stubbing its lazy app-internal imports.
# --------------------------------------------------------------------------- #
_MODULE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "app", "services", "skill_authoring.py",
)


class _FakeSkill:
    """Stand-in for app.models.skill.Skill: stores kwargs, gives a fixed id."""

    _next = 1

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.id = "skill-%d" % _FakeSkill._next
        _FakeSkill._next += 1


class _Flags:
    SKILLS = False


# Records every add_skill_file(...) call made by the write path's auto-emit.
_ADD_FILE_CALLS = []


def _fake_extract_skill_fields(skill_md):
    """Minimal stand-in for app.ai.skills.frontmatter.extract_skill_fields.

    Parses a leading YAML-frontmatter block (---\\n key: value ... \\n---) for the
    handful of keys the authoring service reads. Deliberately tiny: just enough
    to drive the parser under --noconftest without the real frontmatter module
    (which a sibling agent owns) being on disk yet. The production import path is
    the real ``from app.ai.skills.frontmatter import extract_skill_fields``.
    """
    out = {
        "name": "",
        "description": "",
        "allowed_tools": [],
        "disallowed_tools": [],
        "disable_model_invocation": False,
        "user_invocable": True,
        "metadata": {},
        "license": None,
        "body": "",
    }
    text = (skill_md or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        # No frontmatter -> signal "nothing extracted" so the service falls back.
        return out
    # Find the closing delimiter.
    close = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            close = i
            break
    if close is None:
        return out
    for line in lines[1:close]:
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if key == "name":
            out["name"] = val
        elif key == "description":
            out["description"] = val
        elif key == "license":
            out["license"] = val or None
        elif key == "allowed-tools" or key == "allowed_tools":
            out["allowed_tools"] = [t.strip() for t in val.split(",") if t.strip()]
        elif key == "disable-model-invocation":
            out["disable_model_invocation"] = val.lower() == "true"
    out["body"] = "\n".join(lines[close + 1:]).strip()
    return out


def _install_stub_modules(skills_on):
    """Install fake app.settings.hybrid_flags + app.models.skill +
    app.ai.skills.frontmatter in sys.modules."""
    _Flags.SKILLS = bool(skills_on)

    flags_mod = types.ModuleType("app.settings.hybrid_flags")
    flags_mod.flags = _Flags
    sys.modules["app.settings.hybrid_flags"] = flags_mod

    skill_mod = types.ModuleType("app.models.skill")
    skill_mod.Skill = _FakeSkill
    sys.modules["app.models.skill"] = skill_mod

    # Stub the sibling-owned frontmatter module so the YAML path is exercised
    # standalone (real module not on disk yet under --noconftest on py3.9).
    # Registered by its FULLY-QUALIFIED name so the import resolves from
    # sys.modules WITHOUT shadowing the real app.ai / app.ai.skills packages
    # (the distill path imports the real app.ai.brain.qa_pair, which lives under
    # them — stubbing those parents with empty __path__ would break it).
    fm_mod = types.ModuleType("app.ai.skills.frontmatter")
    fm_mod.extract_skill_fields = _fake_extract_skill_fields
    sys.modules["app.ai.skills.frontmatter"] = fm_mod

    # Stub the qa_pair resolver the write path imports. Mirrors Dash's
    # two-sibling-row resolution, but for the test's single-row completion
    # fixtures we just read prompt.content (question) + completion.content
    # (answer). Registered by fully-qualified name so it resolves from
    # sys.modules without needing the real app.ai.brain package to load.
    qa_mod = types.ModuleType("app.ai.brain.qa_pair")

    def _content(obj):
        if isinstance(obj, dict):
            return str(obj.get("content") or "")
        if isinstance(obj, str):
            return obj
        return ""

    async def _resolve_qa_pair(db, completion):
        return (
            _content(getattr(completion, "prompt", None)),
            _content(getattr(completion, "completion", None)),
        )

    qa_mod.resolve_qa_pair = _resolve_qa_pair
    sys.modules["app.ai.brain.qa_pair"] = qa_mod

    # Stub the sibling-owned bundled-files module (app.ai.skills.files). The
    # write path lazily imports add_skill_file to auto-emit proven SQL as a
    # script file; record every call so the test can assert path/kind. Reset
    # the recorder on each install so per-test assertions are isolated.
    files_mod = types.ModuleType("app.ai.skills.files")
    files_mod.KIND_SCRIPT = "script"
    files_mod.KIND_REFERENCE = "reference"
    files_mod.KIND_ASSET = "asset"
    _ADD_FILE_CALLS.clear()

    async def _add_skill_file(db, *, skill_id, path, kind, content):
        _ADD_FILE_CALLS.append(
            {"skill_id": skill_id, "path": path, "kind": kind, "content": content}
        )
        return "file-1"

    async def _list_skill_files(db, *, skill_id):
        return []

    files_mod.add_skill_file = _add_skill_file
    files_mod.list_skill_files = _list_skill_files
    sys.modules["app.ai.skills.files"] = files_mod

    # Ensure parent packages exist so dotted import resolves. NOTE: only stub
    # packages with NO real submodule the service needs — never app.ai/app.ai.skills.
    for pkg in ("app", "app.settings", "app.models"):
        if pkg not in sys.modules:
            m = types.ModuleType(pkg)
            m.__path__ = []  # mark as package
            sys.modules[pkg] = m


def _load_module(skills_on=True):
    _install_stub_modules(skills_on)
    spec = importlib.util.spec_from_file_location(
        "_skill_authoring_under_test", _MODULE_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Load once for the pure-function tests; write tests reload to toggle the flag.
skill_authoring = _load_module(skills_on=True)


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Fakes for the async DB.
# --------------------------------------------------------------------------- #
class _FakeDB:
    def __init__(self):
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.commits += 1

    async def flush(self):
        pass

    async def rollback(self):
        self.rollbacks += 1


class _SpyLLM:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def __call__(self, prompt):
        self.calls.append(prompt)
        return self.reply


_ORG = SimpleNamespace(id="org1")
_USER = SimpleNamespace(id="u1")
_MODEL = object()


def _completion(question="Top stores by revenue this month?", answer="Store A, B, C lead."):
    return SimpleNamespace(
        prompt={"content": question},
        completion={"content": answer},
        report_id="r1",
        turn_index=0,
    )


_GOOD_DRAFT = (
    "NAME: top-stores-by-revenue\n"
    "DESCRIPTION: use when ranking stores by total revenue for a period\n"
    "---\n"
    "1. Pick the period.\n"
    "2. Sum revenue per store.\n"
    "3. Order descending and take the top N.\n"
    "```sql\nSELECT store, SUM(revenue) FROM sales GROUP BY store ORDER BY 2 DESC\n```\n"
)

# Standard Claude-Code-style SKILL.md with YAML frontmatter.
_GOOD_DRAFT_YAML = (
    "---\n"
    "name: top-stores-by-revenue\n"
    "description: use when ranking stores by total revenue for a period\n"
    "---\n"
    "1. Pick the period.\n"
    "2. Sum revenue per store.\n"
    "3. Order descending and take the top N.\n"
    "```sql\nSELECT store, SUM(revenue) FROM sales GROUP BY store ORDER BY 2 DESC\n```\n"
)


# --------------------------------------------------------------------------- #
# 1. build_skill_prompt — pure, with and without SQL
# --------------------------------------------------------------------------- #
def test_build_skill_prompt_with_sql():
    q = "Top stores by revenue?"
    a = "Store A leads."
    sql = "SELECT store, SUM(revenue) FROM sales GROUP BY store"
    p = skill_authoring.build_skill_prompt(q, a, sql)
    assert isinstance(p, str) and p.strip()
    assert q in p
    assert a in p
    assert sql in p
    # New contract: standard SKILL.md with YAML frontmatter.
    assert "frontmatter" in p.lower()
    assert "name:" in p and "description:" in p and "---" in p


def test_build_skill_prompt_mentions_yaml_frontmatter():
    p = skill_authoring.build_skill_prompt("q", "a", None)
    low = p.lower()
    assert "yaml" in low
    assert "frontmatter" in low
    # The legacy uppercase contract is no longer instructed.
    assert "NAME:" not in p
    assert "DESCRIPTION:" not in p


def test_build_skill_prompt_without_sql_is_deterministic():
    q = "Margin leader?"
    a = "Store B."
    p1 = skill_authoring.build_skill_prompt(q, a, None)
    p2 = skill_authoring.build_skill_prompt(q, a, None)
    assert p1 == p2  # deterministic
    assert "No proven SQL is available" in p1
    assert "```sql" not in p1.split("Output EXACTLY")[0]  # no SQL block injected


# --------------------------------------------------------------------------- #
# 2. parse_skill_draft — happy path / malformed / too-short
# --------------------------------------------------------------------------- #
def test_parse_skill_draft_happy_path():
    out = skill_authoring.parse_skill_draft(_GOOD_DRAFT)
    assert out is not None
    assert out["name"] == "top-stores-by-revenue"
    assert out["description"].startswith("use when")
    assert "SELECT store" in out["skill_md"]
    assert "NAME:" not in out["skill_md"]  # header stripped from the body


def test_parse_skill_draft_accepts_yaml_frontmatter():
    out = skill_authoring.parse_skill_draft(_GOOD_DRAFT_YAML)
    assert out is not None
    assert out["name"] == "top-stores-by-revenue"
    assert out["description"].startswith("use when")
    # Body is the procedural markdown (frontmatter stripped).
    assert "SELECT store" in out["skill_md"]
    assert "name:" not in out["skill_md"]
    # The full SKILL.md (frontmatter included) is preserved for skill_md storage.
    assert out["skill_md_full"].startswith("---")
    assert "name: top-stores-by-revenue" in out["skill_md_full"]
    # Frontmatter fields surface with safe defaults.
    assert out["allowed_tools"] == []
    assert out["disallowed_tools"] == []
    assert out["disable_model_invocation"] is False
    assert out["user_invocable"] is True
    assert out["metadata"] == {}
    assert out["license"] is None


def test_parse_skill_draft_still_accepts_legacy_format():
    # Back-compat: the legacy NAME:/DESCRIPTION:/--- contract still parses.
    out = skill_authoring.parse_skill_draft(_GOOD_DRAFT)
    assert out is not None
    assert out["name"] == "top-stores-by-revenue"
    assert out["description"].startswith("use when")
    assert "SELECT store" in out["skill_md"]
    assert "NAME:" not in out["skill_md"]
    # Legacy carries the same extra-field defaults so the write path is uniform.
    assert out["allowed_tools"] == []
    assert out["user_invocable"] is True
    assert out["license"] is None


def test_parse_skill_draft_slugifies_freeform_name():
    text = (
        "NAME: Top Stores By Revenue\n"
        "DESCRIPTION: use when ranking stores\n"
        "---\n"
        "Step one: do the thing thoroughly and carefully here.\n"
    )
    out = skill_authoring.parse_skill_draft(text)
    assert out is not None
    assert out["name"] == "top-stores-by-revenue"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "just some prose with no contract at all",
        "NAME: x\nDESCRIPTION: y\n",          # no '---' delimiter
        "DESCRIPTION: y\n---\nbody here that is plenty long enough to pass",  # no NAME
        "NAME: x\n---\nbody here that is plenty long enough to pass",         # no DESCRIPTION
    ],
)
def test_parse_skill_draft_malformed_returns_none(text):
    assert skill_authoring.parse_skill_draft(text) is None


def test_parse_skill_draft_too_short_body_returns_none():
    text = "NAME: ok-name\nDESCRIPTION: use when\n---\ntiny\n"  # body < MIN_BODY_LEN
    assert skill_authoring.parse_skill_draft(text) is None


# --------------------------------------------------------------------------- #
# 3. distill_skill_from_completion — flag gate
# --------------------------------------------------------------------------- #
def test_distill_noop_when_flag_off():
    mod = _load_module(skills_on=False)
    llm = _SpyLLM(_GOOD_DRAFT)
    db = _FakeDB()
    out = _run(
        mod.distill_skill_from_completion(
            db,
            completion=_completion(),
            user=_USER,
            organization=_ORG,
            model=_MODEL,
            llm_inference=llm,
        )
    )
    assert out is None
    assert llm.calls == []      # LLM never invoked when flag off
    assert db.added == []       # nothing written


# --------------------------------------------------------------------------- #
# 4. happy path -> inserts a DRAFT PERSONAL authored skill, returns id
# --------------------------------------------------------------------------- #
def test_distill_happy_path_inserts_draft_personal_skill():
    mod = _load_module(skills_on=True)
    llm = _SpyLLM(_GOOD_DRAFT)
    db = _FakeDB()
    out = _run(
        mod.distill_skill_from_completion(
            db,
            completion=_completion(),
            user=_USER,
            organization=_ORG,
            model=_MODEL,
            llm_inference=llm,
            gather_sql_fn=lambda *a, **k: None,   # skip the lazy recall import
        )
    )
    assert isinstance(out, str) and out.startswith("skill-")
    assert len(llm.calls) == 1
    assert db.commits == 1
    assert len(db.added) == 1
    skill = db.added[0]
    # Non-live by construction: PERSONAL + DRAFT + authored, never active.
    assert skill.scope == "personal"
    assert skill.status == "draft"
    assert skill.category == "authored"
    assert skill.owner_user_id == "u1"
    assert skill.organization_id == "org1"
    assert skill.hit_count == 0
    assert skill.name == "top-stores-by-revenue"


def test_distill_yaml_draft_persists_full_md_and_frontmatter_columns():
    mod = _load_module(skills_on=True)
    llm = _SpyLLM(_GOOD_DRAFT_YAML)
    db = _FakeDB()
    out = _run(
        mod.distill_skill_from_completion(
            db,
            completion=_completion(),
            user=_USER,
            organization=_ORG,
            model=_MODEL,
            llm_inference=llm,
            gather_sql_fn=lambda *a, **k: None,
        )
    )
    assert isinstance(out, str) and out.startswith("skill-")
    skill = db.added[0]
    assert skill.scope == "personal"
    assert skill.status == "draft"
    assert skill.category == "authored"
    assert skill.name == "top-stores-by-revenue"
    # Full SKILL.md (with frontmatter) is stored.
    assert skill.skill_md.startswith("---")
    assert "name: top-stores-by-revenue" in skill.skill_md
    # New columns persisted (empty lists/dict -> None; scalars stored directly).
    assert skill.allowed_tools is None
    assert skill.disallowed_tools is None
    assert skill.disable_model_invocation is False
    assert skill.user_invocable is True
    assert skill.skill_metadata is None
    assert skill.license is None


def test_distill_passes_sql_into_prompt_via_gather_fn():
    mod = _load_module(skills_on=True)
    llm = _SpyLLM(_GOOD_DRAFT)
    db = _FakeDB()
    sql = "SELECT 1 FROM proven_query"
    _run(
        mod.distill_skill_from_completion(
            db,
            completion=_completion(),
            user=_USER,
            organization=_ORG,
            model=_MODEL,
            llm_inference=llm,
            gather_sql_fn=lambda *a, **k: sql,
        )
    )
    assert len(llm.calls) == 1
    assert sql in llm.calls[0]   # injected SQL reached the prompt


def test_distill_emits_proven_sql_as_bundled_script_file():
    # S3.2-emit: when the completion has proven SQL, the write path auto-bundles
    # it as a script file at scripts/queries.sql (kind=script) on the new skill.
    mod = _load_module(skills_on=True)
    llm = _SpyLLM(_GOOD_DRAFT)
    db = _FakeDB()
    sql = "SELECT store, SUM(revenue) FROM sales GROUP BY store"
    out = _run(
        mod.distill_skill_from_completion(
            db,
            completion=_completion(),
            user=_USER,
            organization=_ORG,
            model=_MODEL,
            llm_inference=llm,
            gather_sql_fn=lambda *a, **k: sql,
        )
    )
    # Skill still authored + committed exactly as before — emit is additive.
    assert isinstance(out, str) and out.startswith("skill-")
    assert db.commits == 1
    assert len(db.added) == 1
    # add_skill_file was called once for the proven SQL.
    assert len(_ADD_FILE_CALLS) == 1
    call = _ADD_FILE_CALLS[0]
    assert call["path"] == "scripts/queries.sql"
    assert call["kind"] == "script"
    assert call["content"] == sql
    assert call["skill_id"] == db.added[0].id


def test_distill_no_proven_sql_emits_no_file():
    # No proven SQL -> skip the file emit silently; skill still authored.
    mod = _load_module(skills_on=True)
    llm = _SpyLLM(_GOOD_DRAFT)
    db = _FakeDB()
    out = _run(
        mod.distill_skill_from_completion(
            db,
            completion=_completion(),
            user=_USER,
            organization=_ORG,
            model=_MODEL,
            llm_inference=llm,
            gather_sql_fn=lambda *a, **k: None,
        )
    )
    assert isinstance(out, str) and out.startswith("skill-")
    assert _ADD_FILE_CALLS == []


# --------------------------------------------------------------------------- #
# 5. missing question / answer -> short-circuit before the LLM
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "completion",
    [
        SimpleNamespace(prompt={}, completion={"content": "answer"}, report_id="r1", turn_index=0),
        SimpleNamespace(prompt={"content": "q"}, completion={}, report_id="r1", turn_index=0),
    ],
)
def test_distill_missing_question_or_answer_returns_none(completion):
    mod = _load_module(skills_on=True)
    llm = _SpyLLM(_GOOD_DRAFT)
    db = _FakeDB()
    out = _run(
        mod.distill_skill_from_completion(
            db,
            completion=completion,
            user=_USER,
            organization=_ORG,
            model=_MODEL,
            llm_inference=llm,
            gather_sql_fn=lambda *a, **k: None,
        )
    )
    assert out is None
    assert llm.calls == []       # LLM not reached
    assert db.added == []


# --------------------------------------------------------------------------- #
# 6. unparseable draft -> None, nothing written
# --------------------------------------------------------------------------- #
def test_distill_unparseable_draft_returns_none():
    mod = _load_module(skills_on=True)
    llm = _SpyLLM("this is not the contract at all")
    db = _FakeDB()
    out = _run(
        mod.distill_skill_from_completion(
            db,
            completion=_completion(),
            user=_USER,
            organization=_ORG,
            model=_MODEL,
            llm_inference=llm,
            gather_sql_fn=lambda *a, **k: None,
        )
    )
    assert out is None
    assert db.added == []
    assert db.commits == 0


# --------------------------------------------------------------------------- #
# 7. write error -> swallowed, rolled back, returns None
# --------------------------------------------------------------------------- #
def test_distill_swallows_write_error_and_rolls_back():
    mod = _load_module(skills_on=True)
    llm = _SpyLLM(_GOOD_DRAFT)

    class _BoomDB(_FakeDB):
        async def commit(self):
            raise RuntimeError("boom on commit")

    db = _BoomDB()
    out = _run(
        mod.distill_skill_from_completion(
            db,
            completion=_completion(),
            user=_USER,
            organization=_ORG,
            model=_MODEL,
            llm_inference=llm,
            gather_sql_fn=lambda *a, **k: None,
        )
    )
    assert out is None
    assert db.rollbacks == 1     # rolled back on failure
