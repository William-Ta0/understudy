"""The replay result contract returned to the calling agent.

Three terminal statuses, never conflated:

    succeeded         checkpoint verified; `outputs` holds the declared, typed outputs.
    business_outcome  a declared alternative result (e.g. MEMBER_NOT_FOUND). The run worked;
                      the answer is "no". `outcome` says which, with the app's own message.
    failed            the run could not complete. `failure` says at which step, what was
                      expected, what was observed, and where the evidence is.

Recoverable conditions never surface as a status. They are handled inside the run and
listed in `recoveries`, so a caller can see the run was bumpy without having to care.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import Field

from .base import Model


class RunStatus(str, Enum):
    succeeded = "succeeded"
    business_outcome = "business_outcome"
    failed = "failed"


class FailureCode(str, Enum):
    INVALID_INPUT = "INVALID_INPUT"  # caller's params failed the input contract; nothing was touched
    NOT_APPROVED = "NOT_APPROVED"  # capability not approved for unattended use
    POLICY_BLOCKED = "POLICY_BLOCKED"  # a step would violate the allowlist or risk policy
    LOGIN_FAILED = "LOGIN_FAILED"
    UNEXPECTED_SCREEN = "UNEXPECTED_SCREEN"  # not where the flow expects, and no known condition explains it
    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"  # no locator matched: likely UI drift
    TARGET_AMBIGUOUS = "TARGET_AMBIGUOUS"  # locators matched several controls, or disagreed
    CHECKPOINT_FAILED = "CHECKPOINT_FAILED"  # acted, but the expected state never appeared
    APP_ERROR = "APP_ERROR"  # the app reported a server/application error
    RECOVERY_EXHAUSTED = "RECOVERY_EXHAUSTED"  # a recoverable condition kept recurring
    UNEXPECTED_DIALOG = "UNEXPECTED_DIALOG"
    OUTPUT_INVALID = "OUTPUT_INVALID"  # an output was missing or failed its type/pattern
    HUMAN_ABORTED = "HUMAN_ABORTED"
    ESCALATION_TIMEOUT = "ESCALATION_TIMEOUT"
    TIMEOUT = "TIMEOUT"
    INTERNAL_ERROR = "INTERNAL_ERROR"


RETRYABLE = {FailureCode.APP_ERROR, FailureCode.RECOVERY_EXHAUSTED, FailureCode.TIMEOUT, FailureCode.LOGIN_FAILED}


class Failure(Model):
    code: FailureCode
    message: str
    step_id: str | None = None
    step_index: int | None = None
    expected: str | None = None
    observed: str | None = None
    retryable: bool = False
    evidence: dict[str, str] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)


class BusinessOutcome(Model):
    code: str
    description: str
    condition: str
    message: str | None = Field(default=None, description="The app's own message, redacted.")
    step_id: str | None = None
    retryable: bool = False


class RecoveryRecord(Model):
    condition: str
    step_id: str | None
    action: str
    attempt: int
    at: datetime


class Warning(Model):
    kind: Literal["locator_drift", "slow_step", "override_applied", "ambiguity"]
    step_id: str | None = None
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class StepRecord(Model):
    id: str
    status: Literal["done", "skipped", "failed", "by_human"]
    duration_ms: int
    locator: str | None = None


class InterventionSummary(Model):
    id: str
    kind: str
    reason: str
    step_id: str | None
    resolution: str | None
    operator: str | None
    human_actions: int = 0


class RunResult(Model):
    run_id: str
    capability: dict[str, str]
    tenant: str
    status: RunStatus
    outputs: dict[str, Any] | None = None
    outcome: BusinessOutcome | None = None
    failure: Failure | None = None
    recoveries: list[RecoveryRecord] = Field(default_factory=list)
    warnings: list[Warning] = Field(default_factory=list)
    interventions: list[InterventionSummary] = Field(default_factory=list)
    steps: list[StepRecord] = Field(default_factory=list)
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    evidence_dir: str | None = None
