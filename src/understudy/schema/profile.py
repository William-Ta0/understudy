"""App profile: what we know about a vendor product, shared by every capability and tenant.

A capability says *what to do*. The app profile says how this product behaves at runtime:
how to sign on, how to recognise each screen, and the catalogue of runtime conditions
(error banners, interstitials, timeouts) with a classification and a response for each.
It is written once per vendor product/version and reused across hundreds of tenants.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .base import Model, Risk
from .capability import Step
from .condition import Condition
from .target import Locator, Target

PROFILE_SCHEMA = "understudy/app-profile@1"


class ConditionKind(str, Enum):
    """The error taxonomy. Every runtime condition the replay engine can detect falls in one class.

    business        a legitimate answer the caller must handle ("no such member"). Not a failure.
    recoverable     an incidental interruption the engine handles itself (interstitial, transient
                    host error, session expiry), within a bounded number of attempts.
    human_required  only a person can resolve it (supervisor override, MFA, ambiguous record).
                    The engine escalates and waits on the same live session.
    fatal           the app is broken or in an unknown state. Stop and surface a debuggable failure.
    """

    business = "business"
    recoverable = "recoverable"
    human_required = "human_required"
    fatal = "fatal"


class Recovery(Model):
    do: Literal["click", "dialog_accept", "dialog_dismiss", "wait", "reload", "relogin"]
    target: Target | None = None
    max_attempts: int = Field(default=2, ge=1, le=5)
    backoff_ms: list[int] = Field(default_factory=lambda: [500, 1500])

    @model_validator(mode="after")
    def _target(self) -> Recovery:
        if self.do == "click" and self.target is None:
            raise ValueError("a click recovery needs a target")
        return self


class RuntimeCondition(Model):
    id: str
    kind: ConditionKind
    description: str
    when: Condition
    code: str | None = Field(default=None, description="Code surfaced to the caller for business/fatal conditions.")
    detail: Target | None = Field(default=None, description="Element whose text is captured as the message.")
    recover: Recovery | None = None
    screens: list[str] | None = Field(default=None, description="Only evaluated on these screens (None: everywhere).")
    priority: int = Field(default=50, description="Lower is checked first. Session and fatal checks go first.")

    @model_validator(mode="after")
    def _shape(self) -> RuntimeCondition:
        if self.kind == ConditionKind.recoverable and not self.recover:
            raise ValueError(f"recoverable condition {self.id!r} needs a recover action")
        if self.kind in (ConditionKind.business, ConditionKind.fatal) and not self.code:
            raise ValueError(f"{self.kind.value} condition {self.id!r} needs a code")
        return self


class ScreenDef(Model):
    id: str
    description: str
    when: Condition


class LoginSpec(Model):
    """Deterministic sign-on. Credentials come from `{{secrets.*}}`; the model never sees them."""

    url: str = Field(description="Template, e.g. '{{tenant.base_url}}/signon.asp'.")
    steps: list[Step]
    success: Condition
    failure: Condition | None = Field(default=None, description="Signals rejected credentials.")


class RiskRule(Model):
    """Classifies controls by what a human reads on them. The first matching rule wins."""

    match: Locator
    risk: Risk
    reason: str


class AppProfile(Model):
    schema_: Literal["understudy/app-profile@1"] = Field(default=PROFILE_SCHEMA, alias="schema")
    id: str
    product: str
    versions: str
    surface: Literal["web", "desktop"]
    description: str
    login: LoginSpec
    home: str = Field(description="Screen reached after sign-on.")
    screens: list[ScreenDef]
    conditions: list[RuntimeCondition]
    risk_rules: list[RiskRule] = Field(default_factory=list)

    def screen(self, screen_id: str) -> ScreenDef:
        for s in self.screens:
            if s.id == screen_id:
                return s
        raise KeyError(f"unknown screen {screen_id!r} in profile {self.id}")

    def condition(self, cond_id: str) -> RuntimeCondition:
        for c in self.conditions:
            if c.id == cond_id:
                return c
        raise KeyError(f"unknown runtime condition {cond_id!r} in profile {self.id}")
