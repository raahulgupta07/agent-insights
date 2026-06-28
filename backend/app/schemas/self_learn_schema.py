"""Schemas for per-studio self-learning config (cockpit-controlled cadence).

Stored on ``studio.config['self_learn']`` (no migration). The studio-learn
daemon reads this per studio and only runs a studio when its own cadence is
due — so each agent owner picks how often their agent self-improves
(every 6h / daily / weekly / monthly), gated under the org master switch
``STUDIO_LEARN_DAEMON_ENABLED``.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field

# Allowed cadences. 'off' = never (also implied by enabled=False).
CADENCES = ("6h", "daily", "weekly", "monthly", "off")


class SelfLearnConfig(BaseModel):
    """Per-studio self-learning settings (the stored shape + API body)."""

    enabled: bool = Field(False, description="Master per-agent switch.")
    cadence: str = Field("daily", description="6h | daily | weekly | monthly | off")
    hour_utc: int = Field(
        0, ge=0, le=23,
        description="For daily/weekly/monthly: only run after this UTC hour (0 = midnight).",
    )
    last_run_at: Optional[str] = Field(
        None, description="ISO-8601 UTC of the last completed self-learn tick (read-only)."
    )

    def normalized(self) -> "SelfLearnConfig":
        c = self.cadence if self.cadence in CADENCES else "daily"
        if c == "off":
            return SelfLearnConfig(enabled=False, cadence="off", hour_utc=self.hour_utc, last_run_at=self.last_run_at)
        return SelfLearnConfig(enabled=self.enabled, cadence=c, hour_utc=self.hour_utc, last_run_at=self.last_run_at)


class SelfLearnResponse(BaseModel):
    """GET/PUT response: the config + computed read-only display fields."""

    enabled: bool
    cadence: str
    hour_utc: int
    last_run_at: Optional[str] = None
    next_run_at: Optional[str] = None
    # Whether the org master daemon switch is on (card is informational if off).
    master_enabled: bool = False
    role: Optional[str] = None  # caller's role on this studio (owner/editor/viewer)
