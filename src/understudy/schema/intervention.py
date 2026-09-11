"""Human-in-the-loop records: the intervention request routed to an operator, and its resolution."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from .base import Model

Resolution = Literal["resume", "abort", "approve", "reject", "completed"]


class InterventionRequest(Model):
    id: str
    run_id: str
    mode: Literal["discovery", "replay"]
    kind: Literal["stuck", "approval", "human_required", "failure", "takeover"]
    reason: str
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="capability/goal, step id + intent, screen, frame URLs, recent actions. Redacted.",
    )
    screenshot: str | None = Field(default=None, description="Path to the masked screenshot taken when the run paused.")
    console_url: str | None = None
    options: list[Resolution]
    created_at: datetime


class HumanAction(Model):
    """One thing the operator did in the live session, captured from the page itself."""

    at: datetime
    kind: Literal["click", "input", "select", "key", "submit", "navigate", "dialog"]
    frame: str | None = None
    target: dict[str, Any] = Field(default_factory=dict)
    value: str | None = Field(default=None, description="Redacted by the sensitivity of the field.")


class InterventionResolution(Model):
    request_id: str
    operator: str
    resolution: Resolution
    note: str | None = None
    claimed_at: datetime | None = None
    released_at: datetime
    human_actions: list[HumanAction] = Field(default_factory=list)
