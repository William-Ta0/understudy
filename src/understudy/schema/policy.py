"""Safety policy: the allowlist and risk handling every actor (model, replay, human) runs under."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import Model, Sensitivity
from .profile import RiskRule

POLICY_SCHEMA = "understudy/policy@1"

ActionType = Literal["click", "fill", "select", "check", "press", "wait", "extract", "dialog", "navigate"]


class ModePolicy(Model):
    allowed_actions: list[ActionType]
    irreversible: Literal["block", "require_approval", "allow"] = Field(
        description="block: never. require_approval: pause for a human per invocation. allow: only for approved capabilities."
    )
    max_steps: int = 40
    max_seconds: int = 900


class DataPolicy(Model):
    mask_in_evidence: list[Sensitivity] = Field(default_factory=lambda: [Sensitivity.pii, Sensitivity.financial, Sensitivity.secret])
    mask_for_model: list[Sensitivity] = Field(default_factory=lambda: [Sensitivity.pii, Sensitivity.secret])
    send_screenshots_to_model: bool = True


class Policy(Model):
    schema_: Literal["understudy/policy@1"] = Field(default=POLICY_SCHEMA, alias="schema")
    id: str
    description: str
    allowed_origins: list[str] = Field(description="scheme://host[:port] the browser may talk to. Everything else is aborted.")
    allowed_paths: list[str] = Field(description="Globs on URL path. A navigation must match one.")
    denied_paths: list[str] = Field(default_factory=list, description="Globs that are blocked even if allowed_paths match.")
    discovery: ModePolicy
    replay: ModePolicy
    risk_rules: list[RiskRule] = Field(default_factory=list, description="Global rules, checked after the app profile's.")
    data: DataPolicy = Field(default_factory=DataPolicy)
