import contextlib
from contextvars import ContextVar
from typing import Optional, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_model import LLMModel
from app.models.llm_usage_record import LLMUsageRecord


# --- Ambient usage attribution ------------------------------------------------
# LLM calls happen deep in the agent / tool stack, far from where we know *who*
# triggered the run and *against which report / data source*. Rather than thread
# that context through every LLM(...) constructor, the orchestrator (AgentV2)
# stamps this contextvar once at the start of a run and the recorder reads it
# when it persists a record. Kept next to the recorder so the two stay in sync.


class UsageAttribution(TypedDict, total=False):
    organization_id: Optional[str]
    user_id: Optional[str]
    report_id: Optional[str]
    data_source_id: Optional[str]


_current_attribution: ContextVar[Optional[UsageAttribution]] = ContextVar(
    "llm_usage_attribution", default=None
)


def get_usage_attribution() -> UsageAttribution:
    """Return a snapshot of the current attribution (empty dict if unset)."""
    value = _current_attribution.get()
    return dict(value) if value else {}


def set_usage_attribution(attribution: Optional[UsageAttribution]):
    """Set the ambient attribution, returning the contextvar token for reset."""
    return _current_attribution.set(attribution or None)


def reset_usage_attribution(token) -> None:
    with contextlib.suppress(Exception):
        _current_attribution.reset(token)


class LLMUsageRecorderService:
    """Persist per-call LLM token/cost usage."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def record(
        self,
        *,
        scope: str,
        scope_ref_id: str | None,
        llm_model: LLMModel,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
        organization_id: str | None = None,
        user_id: str | None = None,
        report_id: str | None = None,
        data_source_id: str | None = None,
    ) -> LLMUsageRecord:

        provider_type = llm_model.provider.provider_type if llm_model.provider else ""
        input_cost = self._calc_input_cost(
            llm_model, prompt_tokens, cache_read_tokens, cache_creation_tokens, provider_type
        )
        output_cost = self._calc_output_cost(llm_model, completion_tokens)

        # Attribution: prefer values the caller passed explicitly, else fall back
        # to the ambient contextvar snapshot stamped by AgentV2 at run start.
        # (create_task copies the current context, so this reads the run's values
        # for the normal agent path.) Org is always knowable from the model.
        attribution = get_usage_attribution()
        org_id = organization_id or attribution.get("organization_id") or (
            str(llm_model.organization_id) if getattr(llm_model, "organization_id", None) else None
        )
        user_id = user_id or attribution.get("user_id")
        report_id = report_id or attribution.get("report_id")
        data_source_id = data_source_id or attribution.get("data_source_id")

        record = LLMUsageRecord(
            scope=scope,
            scope_ref_id=scope_ref_id,
            organization_id=org_id,
            user_id=user_id,
            report_id=report_id,
            data_source_id=data_source_id,
            llm_model_id=str(llm_model.id),
            model_id=llm_model.model_id,
            provider_type=provider_type,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
            input_cost_usd=input_cost,
            output_cost_usd=output_cost,
            total_cost_usd=input_cost + output_cost,
        )
        self.db.add(record)
        await self.db.flush()

        return record

    @staticmethod
    def _calc_input_cost(
        llm_model: LLMModel,
        tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
        provider_type: str = "",
    ) -> float:
        rate = llm_model.get_input_cost_rate()
        if rate is None:
            return 0.0
        rate_f = float(rate)
        # Non-cached input tokens at full rate (Anthropic excludes cached tokens
        # from input_tokens; OpenAI includes them, so we handle both below).
        cost = (tokens / 1_000_000) * rate_f if tokens else 0.0
        if provider_type == "anthropic":
            # Cache reads: billed at 0.1× input rate.
            # Cache writes: billed at 1.25× input rate.
            if cache_read_tokens:
                cost += (cache_read_tokens / 1_000_000) * rate_f * 0.1
            if cache_creation_tokens:
                cost += (cache_creation_tokens / 1_000_000) * rate_f * 1.25
        elif provider_type in ("openai", "azure"):
            # OpenAI/Azure include cached tokens in prompt_tokens at full rate,
            # but actually charge 0.5× for those tokens. Apply the 50% discount.
            if cache_read_tokens:
                cost -= (cache_read_tokens / 1_000_000) * rate_f * 0.5
        return max(cost, 0.0)

    @staticmethod
    def _calc_output_cost(llm_model: LLMModel, tokens: int) -> float:
        rate = llm_model.get_output_cost_rate()
        if not tokens or rate is None:
            return 0.0
        return (tokens / 1_000_000) * float(rate)

