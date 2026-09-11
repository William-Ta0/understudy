"""Discovery input (the goal) and output (the trace the compiler turns into a capability).

The trace is the *structured* record of a discovery run, not the model transcript: each
entry is an action on a described target, with the screen before and after, the
locator candidates validated at the moment of the action, and why the actor did it.
The transcript is kept separately (redacted) for audit only; nothing downstream reads it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from .base import Model, Risk, Sensitivity, ValueType
from .capability import OutcomeSpec, ParamSpec
from .condition import Condition

GOAL_SCHEMA = "understudy/goal@1"


class OutputDecl(Model):
    type: ValueType
    description: str
    sensitivity: Sensitivity
    pattern: str | None = None


class Limits(Model):
    max_steps: int = 30
    max_seconds: int = 600


class GoalSpec(Model):
    schema_: Literal["understudy/goal@1"] = Field(default=GOAL_SCHEMA, alias="schema")
    capability: str = Field(description="Id the compiled capability will get.")
    title: str
    goal: str = Field(description="Natural-language goal. May reference {{inputs.x}}.")
    app_profile: str
    entry: str = Field(description="Screen the run starts from after sign-on.")
    inputs: dict[str, ParamSpec] = Field(default_factory=dict)
    outputs: dict[str, OutputDecl] = Field(default_factory=dict)
    outcomes: list[OutcomeSpec] = Field(default_factory=list)
    limits: Limits = Field(default_factory=Limits)


class Candidate(Model):
    locator: dict[str, Any]
    matches: int
    unique: bool
    same: bool


class DescribedTarget(Model):
    """Everything known about an acted-on control at the moment of the action."""

    frame: str | None
    role: str
    name: str = ""
    label: str = ""
    text: str = ""
    tag: str = ""
    inferred: bool = False
    sensitive: str | None = None
    candidates: list[Candidate] = Field(default_factory=list)


class TraceStep(Model):
    index: int
    actor: Literal["agent", "human"]
    purpose: Literal["flow", "incidental", "exploratory"] = "flow"
    action: str
    rationale: str = ""
    screen_before: str | None = None
    screen_after: str | None = None
    target: DescribedTarget | None = None
    value: str | None = Field(default=None, description="Template or redacted literal for fill/select/press/dialog.")
    output: str | None = Field(default=None, description="Output name for extract steps.")
    checkpoint: Condition | None = None
    risk: Risk = Risk.reversible
    ok: bool = True
    error: str | None = None
    frames_after: dict[str, str] = Field(default_factory=dict)
    at: datetime


class InterventionRecord(Model):
    id: str
    kind: str
    reason: str
    at_step: int
    resolution: str | None = None
    operator: str | None = None
    human_steps: list[int] = Field(default_factory=list)


class Finish(Model):
    status: Literal["success", "impossible", "stuck", "aborted", "limit"]
    summary: str
    success: Condition | None = None


class LLMUsage(Model):
    model: str
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0


class Trace(Model):
    run_id: str
    goal: GoalSpec
    tenant: str
    product_version: str
    started_at: datetime
    finished_at: datetime | None = None
    steps: list[TraceStep] = Field(default_factory=list)
    interventions: list[InterventionRecord] = Field(default_factory=list)
    extracted: dict[str, dict[str, str]] = Field(default_factory=dict, description="output -> {sensitivity, fingerprint}")
    finish: Finish | None = None
    llm: LLMUsage | None = None
