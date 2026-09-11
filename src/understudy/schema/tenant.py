"""Tenant binding: one institution's instance of a vendor product.

Capabilities are written against the vendor product in its default vocabulary. A tenant
binding says where the instance lives and how it differs, in three layers, from the
broadest to the most surgical:

    vocabulary            tenant relabels (vendor default text -> this tenant's text). Applied to
                          every locator and checkpoint of every capability for this app, so a
                          renamed field is fixed once per tenant, not once per capability.
    conditions / screens  tenant-specific runtime conditions (e.g. a mandatory daily bulletin) and
                          screen-signature overrides, merged over the app profile.
    capability_overrides  a replacement Target for a specific step or output of a specific
                          capability, for the rare structural difference vocabulary can't express.

Every override applied during a run is listed in the run result, so drift stays visible.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import Model
from .profile import RuntimeCondition, ScreenDef
from .target import Target

TENANT_SCHEMA = "understudy/tenant@1"


class CapabilityOverride(Model):
    targets: dict[str, Target] = Field(
        default_factory=dict,
        description="Key is a step id, or 'output:<name>' for an output source.",
    )
    reason: str


class TenantBinding(Model):
    schema_: Literal["understudy/tenant@1"] = Field(default=TENANT_SCHEMA, alias="schema")
    id: str
    name: str
    app_profile: str
    product_version: str
    base_url: str
    credentials: str = Field(description="Reference only, e.g. 'env:KEYSTONE_LAKESHORE'. Never an inline secret.")
    vocabulary: dict[str, str] = Field(default_factory=dict)
    conditions: list[RuntimeCondition] = Field(default_factory=list)
    screens: list[ScreenDef] = Field(default_factory=list)
    capability_overrides: dict[str, CapabilityOverride] = Field(default_factory=dict)
