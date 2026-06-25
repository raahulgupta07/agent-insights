"""Embeddings client (OpenRouter / OpenAI-compatible) for Hybrid Search.

Reuses the org's existing LLM provider credentials — OpenRouter exposes an
OpenAI-compatible ``/embeddings`` endpoint, so no separate provider or key is
needed. Default model ``openai/text-embedding-3-small`` (1536-dim), which matches
the ``knowledge_search_index.embedding vector(1536)`` column → zero migration.

Everything is fail-soft: any error returns None / [] so the caller falls back to
the vectorless FTS + Jaccard path. Gated by flags.SEMANTIC_SEARCH at the call
sites (indexer / hybrid_search), not here.

Config (env, optional):
    HYBRID_EMBED_MODEL   default "openai/text-embedding-3-small"
    HYBRID_EMBED_DIM     default 1536  (must match the DB column dimension)
    HYBRID_EMBED_BATCH   default 96    (texts per API call)
"""
from __future__ import annotations

import os
import logging
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)

EMBED_MODEL = os.environ.get("HYBRID_EMBED_MODEL", "openai/text-embedding-3-small")
EMBED_DIM = int(os.environ.get("HYBRID_EMBED_DIM", "1536"))
_BATCH = int(os.environ.get("HYBRID_EMBED_BATCH", "96"))


async def _resolve_provider(db, organization) -> Optional[Tuple[str, str]]:
    """Return (api_key, base_url) from the org's default/first enabled model.

    Reuses the same provider credentials the chat path uses (OpenRouter/custom →
    OpenAI-compatible). Returns None if no usable provider/key is found.
    """
    try:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from app.models.llm_model import LLMModel

        org_id = str(getattr(organization, "id", None) or "")
        if not org_id:
            return None

        stmt = (
            select(LLMModel)
            .options(selectinload(LLMModel.provider))
            .where(LLMModel.organization_id == org_id, LLMModel.is_enabled == True)  # noqa: E712
            .order_by(LLMModel.is_default.desc())
            .limit(1)
        )
        model = (await db.execute(stmt)).scalars().first()
        if model is None or model.provider is None:
            return None

        provider = model.provider
        try:
            api_key = provider.decrypt_credentials()[0]
        except Exception:
            api_key = None

        cfg = getattr(provider, "additional_config", None) or {}
        base_url = cfg.get("base_url") if isinstance(cfg, dict) else None
        if not base_url:
            # OpenRouter has a fixed host; other OpenAI-native providers use the
            # SDK default, so only OpenRouter/custom (with base_url) are usable
            # for the OpenAI-compatible embeddings endpoint here.
            if (getattr(provider, "provider_type", "") or "") == "openrouter":
                base_url = "https://openrouter.ai/api/v1"
        if not base_url or not api_key:
            return None
        return (api_key, base_url)
    except Exception as exc:
        log.debug("embeddings: provider resolve failed (%s)", exc)
        return None


async def _embed_with(api_key: str, base_url: str, texts: List[str]) -> List[List[float]]:
    """Call the OpenAI-compatible /embeddings endpoint in batches. Fail-soft."""
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    out: List[List[float]] = []
    for i in range(0, len(texts), _BATCH):
        batch = [(t or " ")[:8000] for t in texts[i:i + _BATCH]]
        try:
            resp = await client.embeddings.create(
                model=EMBED_MODEL, input=batch, encoding_format="float"
            )
            out.extend([d.embedding for d in resp.data])
        except Exception as exc:
            log.warning("embeddings: batch %d failed (%s)", i // _BATCH, exc)
            out.extend([[] for _ in batch])
    return out


async def embed_texts(db, organization, texts: List[str]) -> List[List[float]]:
    """Embed a list of texts for an org. Returns [] (or per-item []) on failure."""
    if not texts:
        return []
    creds = await _resolve_provider(db, organization)
    if not creds:
        log.info("embeddings: no usable provider/key for org — skipping vectors")
        return [[] for _ in texts]
    api_key, base_url = creds
    return await _embed_with(api_key, base_url, texts)


async def embed_query(db, organization, text: str) -> Optional[List[float]]:
    """Embed a single query string. Returns None on any failure."""
    if not text:
        return None
    vecs = await embed_texts(db, organization, [text])
    if vecs and vecs[0]:
        return vecs[0]
    return None


def to_pgvector_literal(vec: List[float]) -> Optional[str]:
    """Format a python float list as a pgvector literal '[0.1,0.2,...]'."""
    if not vec:
        return None
    return "[" + ",".join(f"{float(x):.6f}" for x in vec) + "]"
