"""The capability artifact: a typed, versioned, reviewable contract plus the flow that fulfils it.

Reading order for a reviewer (and the order of the YAML file):

    identity      id, version, status, app it targets
    contract      inputs, outputs, outcomes: what a calling agent supplies, gets back, and must handle
    flow          entry screen, ordered steps (each with its target, checkpoint, and risk), success condition
    evidence      provenance (how it was discovered and verified) and review notes

The contract is deliberately separate from the flow: a caller only needs the contract,
and the flow can be re-recorded or overridden per tenant without changing it.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .base import Model, Risk, Sensitivity, Text, ValueType
from .condition import Condition
from .target import SEMANTIC, Target

CAPABILITY_SCHEMA = "understudy/capability@1"
ID_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
STEP_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


# --------------------------------------------------------------------------- contract


class ParamSpec(Model):
    """One typed input the calling agent supplies per invocation."""

    type: ValueType
    description: str
    required: bool = True
    pattern: str | None = None
    enum: list[str] | None = None
    minimum: Decimal | None = None
    maximum: Decimal | None = None
    sensitivity: Sensitivity = Sensitivity.internal
    example: str | None = Field(default=None, description="Only allowed for public/internal inputs.")

    @model_validator(mode="after")
    def _check(self) -> ParamSpec:
        if self.type == ValueType.enum and not self.enum:
            raise ValueError("enum inputs must list their values")
        if self.example is not None and self.sensitivity.masked:
            raise ValueError(f"inputs with sensitivity={self.sensitivity.value} may not carry an example value")
        return self


class OutputSpec(Model):
    """One typed value returned to the caller, and where on screen it is read from."""

    type: ValueType
    description: str
    sensitivity: Sensitivity
    source: Target
    read: Literal["text", "value"] = "text"
    pattern: str | None = Field(default=None, description="Raw text must match this regex before parsing.")
    required: bool = True

    @field_validator("source")
    @classmethod
    def _semantic_only(cls, v: Target) -> Target:
        # A wrong read returns wrong data with no error, so outputs may not fall back to structural locators.
        bad = [loc.by for loc in v.locators if loc.by not in SEMANTIC]
        if bad:
            raise ValueError(f"output sources may only use semantic locators ({sorted(SEMANTIC)}), got {bad}")
        return v


class OutcomeSpec(Model):
    """An expected, legitimate result other than success. Not an error: the caller must handle it."""

    code: str = Field(description="UPPER_SNAKE code returned to the caller, e.g. MEMBER_NOT_FOUND.")
    description: str
    condition: str = Field(description="Id of the app-profile runtime condition that signals this outcome.")
    retryable: bool = False

    @field_validator("code")
    @classmethod
    def _code(cls, v: str) -> str:
        if not CODE_RE.match(v):
            raise ValueError("outcome codes are UPPER_SNAKE_CASE")
        return v


# --------------------------------------------------------------------------- flow


class StepBase(Model):
    id: str = Field(description="Stable snake_case id. Used by overrides, logs, drift reports, and resume.")
    intent: str = Field(description="What this step does and why, for reviewers.")
    screen: str | None = Field(default=None, description="Precondition: the app-profile screen this step acts on.")
    expect: Condition | None = Field(default=None, description="Checkpoint that must hold after the action.")
    timeout_ms: int = Field(default=15000, ge=100, le=300000)
    risk: Risk = Risk.reversible
    approval: Literal["none", "required"] = Field(default="none", description="'required' pauses for a human before acting.")
    origin: Literal["agent", "human", "reviewer"] = Field(default="agent", description="Who performed this step at discovery.")

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not STEP_ID_RE.match(v):
            raise ValueError("step ids are snake_case")
        return v

    @model_validator(mode="after")
    def _irreversible_needs_approval(self) -> StepBase:
        if self.risk == Risk.irreversible and self.approval != "required":
            raise ValueError(f"step {self.id!r} is irreversible and must declare approval: required")
        return self


class ClickStep(StepBase):
    action: Literal["click"] = "click"
    target: Target


class FillStep(StepBase):
    action: Literal["fill"] = "fill"
    target: Target
    value: str = Field(description="Template, e.g. '{{inputs.member_id}}'. Literal constants are flagged in review.")


class SelectStep(StepBase):
    action: Literal["select"] = "select"
    target: Target
    option: str = Field(description="Option label to choose (template). Matched exactly, case-insensitive.")


class CheckStep(StepBase):
    action: Literal["check"] = "check"
    target: Target
    checked: bool = True


class PressStep(StepBase):
    action: Literal["press"] = "press"
    key: str
    target: Target | None = None


class WaitStep(StepBase):
    """A pure checkpoint: wait until the condition holds (or a runtime condition fires)."""

    action: Literal["wait"] = "wait"
    risk: Risk = Risk.read
    until: Condition


class ExtractStep(StepBase):
    """Read the named outputs from the current screen."""

    action: Literal["extract"] = "extract"
    risk: Risk = Risk.read
    outputs: list[str]


class DialogStep(StepBase):
    """Answer a native dialog that is an expected part of the flow (unexpected ones are runtime conditions)."""

    action: Literal["dialog"] = "dialog"
    response: Literal["accept", "dismiss"]
    message: Text | None = None


Step = Annotated[
    ClickStep | FillStep | SelectStep | CheckStep | PressStep | WaitStep | ExtractStep | DialogStep,
    Field(discriminator="action"),
]


# --------------------------------------------------------------------------- identity / lifecycle


class AppRef(Model):
    product: str = Field(description="Vendor product the flow is written against, e.g. keystone-core.")
    profile: str = Field(description="App profile id providing screens, runtime conditions, and login.")
    versions: str = Field(description="Compatible product versions, e.g. '>=7.0,<8'.")


class Entry(Model):
    screen: str = Field(description="Screen the flow starts from, in an authenticated session.")


class Lifecycle(str, Enum):
    """draft: compiled, never replayed. verified: replayed without the model at least once.
    approved: a human reviewed it; agents may invoke it unattended. deprecated: kept for audit."""

    draft = "draft"
    verified = "verified"
    approved = "approved"
    deprecated = "deprecated"


class Approval(Model):
    by: str
    at: datetime
    content_hash: str
    note: str | None = None


class ReviewNote(Model):
    level: Literal["info", "warning", "blocker"]
    step: str | None = None
    message: str


class Review(Model):
    notes: list[ReviewNote] = Field(default_factory=list)
    approvals: list[Approval] = Field(default_factory=list)


class DiscoveryInfo(Model):
    run_id: str
    goal: str
    model: str
    tenant: str
    product_version: str
    at: datetime
    agent_steps: int
    human_steps: int = 0
    llm_calls: int = 0


class VerificationRecord(Model):
    run_id: str
    at: datetime
    tenant: str
    status: str
    duration_ms: int


class Provenance(Model):
    discovered: DiscoveryInfo | None = None
    compiled_by: str
    trace_digest: str | None = None
    verifications: list[VerificationRecord] = Field(default_factory=list)


# --------------------------------------------------------------------------- the artifact


class Capability(Model):
    schema_: Literal["understudy/capability@1"] = Field(default=CAPABILITY_SCHEMA, alias="schema")
    id: str
    version: str
    title: str
    description: str
    status: Lifecycle = Lifecycle.draft
    app: AppRef

    inputs: dict[str, ParamSpec] = Field(default_factory=dict)
    outputs: dict[str, OutputSpec] = Field(default_factory=dict)
    outcomes: list[OutcomeSpec] = Field(default_factory=list)

    entry: Entry
    steps: list[Step] = Field(min_length=1)
    success: Condition
    risk: Risk = Field(description="Highest risk of any step. Derived; checked on load.")

    provenance: Provenance
    review: Review = Field(default_factory=Review)

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not ID_RE.match(v):
            raise ValueError("capability ids are dotted snake_case, e.g. keystone.member.lookup_balance")
        return v

    @field_validator("version")
    @classmethod
    def _semver(cls, v: str) -> str:
        if not SEMVER_RE.match(v):
            raise ValueError("version must be semver MAJOR.MINOR.PATCH")
        return v

    @model_validator(mode="after")
    def _consistency(self) -> Capability:
        ids = [s.id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("step ids must be unique")
        extracted = {o for s in self.steps if isinstance(s, ExtractStep) for o in s.outputs}
        missing = set(self.outputs) - extracted
        if missing:
            raise ValueError(f"outputs never extracted by any step: {sorted(missing)}")
        unknown = extracted - set(self.outputs)
        if unknown:
            raise ValueError(f"extract steps reference undeclared outputs: {sorted(unknown)}")
        used = _templates_in(self)
        undeclared = {u for u in used if u.startswith("inputs.") and u.split(".", 1)[1] not in self.inputs}
        if undeclared:
            raise ValueError(f"templates reference undeclared inputs: {sorted(undeclared)}")
        top = max((s.risk for s in self.steps), key=lambda r: r.rank)
        if top != self.risk:
            raise ValueError(f"capability risk is {self.risk.value} but its riskiest step is {top.value}")
        return self

    # The hash covers behaviour only. Approvals bind to it, so editing a step after approval
    # silently invalidates the approval instead of silently inheriting it.
    def content_hash(self) -> str:
        body = self.dump()
        behaviour = {k: body.get(k) for k in ("id", "app", "inputs", "outputs", "outcomes", "entry", "steps", "success")}
        canon = json.dumps(behaviour, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(canon.encode()).hexdigest()

    def is_approved(self) -> bool:
        h = self.content_hash()
        return self.status == Lifecycle.approved and any(a.content_hash == h for a in self.review.approvals)

    def step(self, step_id: str) -> Step:
        for s in self.steps:
            if s.id == step_id:
                return s
        raise KeyError(step_id)


_TEMPLATE_RE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


def _templates_in(obj: object) -> set[str]:
    found: set[str] = set()

    def walk(x: object) -> None:
        if isinstance(x, str):
            found.update(_TEMPLATE_RE.findall(x))
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    if isinstance(obj, Model):
        walk(obj.dump())
    else:
        walk(obj)
    return found
