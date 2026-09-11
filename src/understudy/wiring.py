"""Composition: load a tenant's effective view, open a surface under policy, and run things on it."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .evidence import Evidence
from .hitl.control import ControlCenter, LiveSession
from .registry import CapabilityStore, effective_capability, effective_profile, load_policy, load_profile, load_tenant, workspace
from .replay.engine import ReplayEngine, ReplayOptions
from .safety.policy import PolicyGuard
from .safety.redact import Redactor
from .schema import AppProfile, Capability, Policy, RunResult, TenantBinding
from .surface.web import WebSurface


def load_env() -> None:
    load_dotenv(workspace() / ".env", override=False)


@dataclass
class Env:
    tenant: TenantBinding
    profile: AppProfile
    policy: Policy
    guard: PolicyGuard
    redactor: Redactor
    evidence: Evidence
    surface: WebSurface
    session: LiveSession | None

    async def close(self) -> None:
        self.evidence.close()
        await self.surface.close()


def evidence_root() -> Path:
    return Path(os.environ.get("UNDERSTUDY_EVIDENCE_DIR", workspace() / "evidence" / "runs"))


async def open_env(tenant_id: str, *, kind: str, label: str, control: ControlCenter | None = None,
                   headless: bool = True, policy_id: str = "default", evidence_dir: Path | None = None) -> Env:
    load_env()
    tenant = load_tenant(tenant_id)
    profile = effective_profile(load_profile(tenant.app_profile), tenant)
    policy = load_policy(policy_id)
    guard = PolicyGuard(policy, profile)
    redactor = Redactor()
    evidence = Evidence(evidence_dir or evidence_root(), kind, label, redactor)
    surface = await WebSurface.launch(headless=headless, url_guard=guard.url_allowed)
    surface.on_blocked = lambda url, why: evidence.event("policy_blocked_request", url=url, reason=why)
    session = control.open(evidence.run_id, "replay" if kind == "replay" else "discovery", label, surface, evidence, redactor) if control else None
    return Env(tenant, profile, policy, guard, redactor, evidence, surface, session)


async def run_replay(cap_ref: str | Capability, tenant_id: str, inputs: dict[str, Any], *,
                     options: ReplayOptions | None = None, control: ControlCenter | None = None, headless: bool = True,
                     label: str | None = None, evidence_dir: Path | None = None, tenant_overrides: bool = True) -> RunResult:
    cap = cap_ref if isinstance(cap_ref, Capability) else CapabilityStore().load(cap_ref)
    env = await open_env(tenant_id, kind="replay", label=label or cap.id.split(".")[-1], control=control,
                         headless=headless, evidence_dir=evidence_dir)
    try:
        if tenant_overrides:
            eff, applied = effective_capability(cap, env.tenant)
        else:  # the capability exactly as recorded; the app profile stays tenant-aware
            eff, applied = cap, ["capability-level tenant vocabulary and overrides disabled for this run"]
        engine = ReplayEngine(eff, env.profile, env.tenant, env.guard, env.surface, env.evidence, env.redactor,
                              env.session, options or ReplayOptions(), applied)
        return await engine.run(inputs)
    finally:
        if control and env.session:
            control.close(env.evidence.run_id)
        await env.close()
