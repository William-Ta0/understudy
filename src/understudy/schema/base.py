"""Shared building blocks for every understudy document."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class Model(BaseModel):
    """Strict base: unknown keys are errors, so a typo in a reviewed YAML file never passes silently."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True, use_enum_values=False)

    def dump(self) -> dict:
        """Canonical, JSON-safe, compact form used for YAML/JSON files."""
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


class Sensitivity(str, Enum):
    """How a value may be handled. Drives redaction in logs, evidence, and what the model sees.

    public     product names, labels. Safe anywhere.
    internal   operational identifiers (a member number). Logged; not masked.
    pii        personal data (name, SSN, DOB, address, contact). Masked in logs, evidence, and model input.
    financial  nonpublic financial data (balances, amounts). Treated like pii.
    secret     credentials, override codes. Never logged, never shown to the model, never persisted.
    """

    public = "public"
    internal = "internal"
    pii = "pii"
    financial = "financial"
    secret = "secret"

    @property
    def masked(self) -> bool:
        return self in (Sensitivity.pii, Sensitivity.financial, Sensitivity.secret)


class TextMatch(Model):
    """A text predicate. Comparison is always whitespace- and case-insensitive.

    `value` may contain templates such as `{{inputs.member_id}}`; they are rendered before matching.
    A bare string in YAML means `mode: exact` for locators and `mode: contains` for text conditions.
    """

    value: str
    mode: Literal["exact", "contains", "regex"] = "exact"


Text = str | TextMatch


class Scope(Model):
    """One level of container path, outermost first. Exactly one field is set.

    frame   a frame/iframe, by its `name` attribute (web). Vendor-level, so stable across tenants.
    dialog  an in-page modal by (partial) title; "" means any open dialog.
    window  a top-level window by title (desktop surfaces; not implemented for web).
    """

    frame: str | None = None
    dialog: str | None = None
    window: str | None = None

    @model_validator(mode="after")
    def _one(self) -> Scope:
        if sum(v is not None for v in (self.frame, self.dialog, self.window)) != 1:
            raise ValueError("a scope sets exactly one of frame / dialog / window")
        return self

    def __str__(self) -> str:
        for k in ("frame", "dialog", "window"):
            v = getattr(self, k)
            if v is not None:
                return f"{k}:{v}"
        return "?"


class ValueType(str, Enum):
    string = "string"
    integer = "integer"
    decimal = "decimal"
    money = "money"  # a decimal amount in the institution's currency; parsed from "$1,234.56"
    date = "date"  # ISO 8601 on the wire; parsed from the app's display format
    boolean = "boolean"
    enum = "enum"


class Risk(str, Enum):
    """Effect of a step on the system of record.

    read          no effect (extract, wait, checkpoint).
    reversible    navigation, form input, or a submit that does not commit a business change.
    irreversible  commits a business change (post, open, close, transfer). Gated by policy.
    """

    read = "read"
    reversible = "reversible"
    irreversible = "irreversible"

    @property
    def rank(self) -> int:
        return {"read": 0, "reversible": 1, "irreversible": 2}[self.value]
