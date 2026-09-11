"""Sessions and sign-on. Credentials are resolved from a reference at run time and never persisted.

The model never signs on and never sees a credential: sign-on is a deterministic routine
from the app profile, run before discovery or replay starts (and again if a session
expires). Secrets are registered with the redactor before use.
"""

from __future__ import annotations

import asyncio
import os
import time

from ..evidence import Evidence
from ..schema import AppProfile, ClickStep, ConditionKind, FillStep, Sensitivity, TenantBinding
from ..surface.web import WebSurface
from .conditions import ConditionEvaluator
from .recovery import Recoverer, RecoveryExhausted
from .values import Renderer


class LoginError(RuntimeError):
    pass


def resolve_credentials(ref: str) -> dict[str, str]:
    """`env:PREFIX` reads PREFIX_USERNAME / PREFIX_PASSWORD. A vault reference would plug in here."""
    scheme, _, name = ref.partition(":")
    if scheme != "env" or not name:
        raise LoginError(f"unsupported credential reference {ref!r} (expected env:PREFIX)")
    user, pwd = os.environ.get(f"{name}_USERNAME"), os.environ.get(f"{name}_PASSWORD")
    if not user or not pwd:
        raise LoginError(f"credentials not configured: set {name}_USERNAME and {name}_PASSWORD (see .env.example)")
    return {"username": user, "password": pwd}


class SessionManager:
    def __init__(self, surface: WebSurface, profile: AppProfile, tenant: TenantBinding, evaluator: ConditionEvaluator,
                 recoverer: Recoverer, evidence: Evidence, redactor_register):
        self.surface = surface
        self.profile = profile
        self.tenant = tenant
        self.evaluator = evaluator
        self.recoverer = recoverer
        self.evidence = evidence
        self._register = redactor_register
        self.sign_ons = 0

    async def sign_on(self, timeout_s: float = 20) -> None:
        creds = resolve_credentials(self.tenant.credentials)
        self._register(creds["password"], Sensitivity.secret, "password")
        render = Renderer(tenant={"base_url": self.tenant.base_url}, secrets=creds)
        self.sign_ons += 1
        self.evidence.event("sign_on_started", tenant=self.tenant.id, attempt=self.sign_ons)
        await self.surface.goto(render(self.profile.login.url))
        await self.surface.settle()
        for step in self.profile.login.steps:
            if not isinstance(step, (FillStep, ClickStep)):
                raise LoginError(f"unsupported login step {step.action}")
            res = None
            for _ in range(40):
                res = await self.surface.resolve(step.target)
                if res.found:
                    break
                await asyncio.sleep(0.25)
            if res is None or not res.found:
                raise LoginError(f"sign-on control not found: {step.target.description}")
            if isinstance(step, FillStep):
                await self.surface.fill(res, render(step.value))
            else:
                await self.surface.click(res)
                await self.surface.settle()
            self.evidence.event("sign_on_step", step=step.id)  # never the value
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if await self.evaluator.holds(self.profile.login.success):
                self.evidence.event("sign_on_completed", screen=self.profile.home)
                return
            det = await self.evaluator.detect()
            # A "session expired" condition is expected while we are still on the sign-on page: skip relogin rules.
            if det and not (det.condition.recover and det.condition.recover.do == "relogin"):
                rc = det.condition
                self.evidence.event("condition_detected", id=rc.id, kind=rc.kind.value, phase="sign_on", message=det.message)
                if rc.kind == ConditionKind.recoverable and rc.recover and rc.recover.do != "relogin":
                    try:
                        await self.recoverer.recover(rc, step_id="sign_on")
                    except RecoveryExhausted as e:
                        raise LoginError(str(e)) from e
                    continue
                raise LoginError(f"sign-on blocked by {rc.id}: {det.message or rc.description}")
            if self.profile.login.failure and await self.evaluator.holds(self.profile.login.failure):
                raise LoginError("the app rejected the credentials")
            await asyncio.sleep(0.25)
        raise LoginError(f"did not reach the home screen ({self.profile.home}) within {timeout_s:.0f}s")
