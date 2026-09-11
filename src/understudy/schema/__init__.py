"""Typed documents: capability artifacts, app profiles, tenant bindings, policy, results, traces."""

from .base import Model, Risk, Scope, Sensitivity, Text, TextMatch, ValueType
from .capability import (
    AppRef,
    Approval,
    Capability,
    CheckStep,
    ClickStep,
    DialogStep,
    Entry,
    ExtractStep,
    FillStep,
    Lifecycle,
    OutcomeSpec,
    OutputSpec,
    ParamSpec,
    PressStep,
    Provenance,
    Review,
    ReviewNote,
    SelectStep,
    Step,
    VerificationRecord,
    WaitStep,
)
from .condition import (
    AllCondition,
    AnyCondition,
    Condition,
    DialogCondition,
    ElementCondition,
    NotCondition,
    ScreenCondition,
    TextCondition,
    UrlCondition,
    summarize,
)
from .intervention import HumanAction, InterventionRequest, InterventionResolution
from .policy import Policy
from .profile import AppProfile, ConditionKind, Recovery, RiskRule, RuntimeCondition, ScreenDef
from .result import (
    BusinessOutcome,
    Failure,
    FailureCode,
    InterventionSummary,
    RecoveryRecord,
    RunResult,
    RunStatus,
    StepRecord,
    Warning,
)
from .target import (
    AttrLocator,
    CssLocator,
    LabelLocator,
    Locator,
    PointLocator,
    RoleLocator,
    TableCellLocator,
    Target,
    TextLocator,
    describe_locator,
)
from .tenant import CapabilityOverride, TenantBinding
from .trace import DescribedTarget, GoalSpec, OutputDecl, Trace, TraceStep

__all__ = [name for name in dir() if not name.startswith("_")]
