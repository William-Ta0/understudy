"""Executing the response to a detected runtime condition (shared by sign-on, replay, and discovery)."""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import datetime, timezone

from ..evidence import Evidence
from ..safety.policy import PolicyGuard
from ..schema import RecoveryRecord, RuntimeCondition
from ..surface.web import WebSurface
from .values import Renderer


class RecoveryExhausted(RuntimeError):
    def __init__(self, condition: RuntimeCondition, attempts: int, why: str = ""):
        super().__init__(f"{condition.id} persisted after {attempts} recovery attempt(s){': ' + why if why else ''}")
        self.condition = condition
        self.attempts = attempts


class Recoverer:
    def __init__(self, surface: WebSurface, guard: PolicyGuard, evidence: Evidence, render: Renderer, *,
                 mode: str = "replay"):
        self.surface = surface
        self.guard = guard
        self.evidence = evidence
        self.render = render
        self.mode = mode
        self.attempts: Counter[str] = Counter()
        self.records: list[RecoveryRecord] = []

    async def recover(self, rc: RuntimeCondition, step_id: str | None) -> None:
        """Perform `rc.recover` once. `relogin` is the caller's job (it implies restarting the flow)."""
        assert rc.recover is not None
        spec = rc.recover
        self.attempts[rc.id] += 1
        n = self.attempts[rc.id]
        if n > spec.max_attempts:
            raise RecoveryExhausted(rc, n - 1)
        delay = spec.backoff_ms[min(n - 1, len(spec.backoff_ms) - 1)] if spec.backoff_ms else 0
        if spec.do == "click":
            await asyncio.sleep(min(delay, 250) / 1000)
        else:
            await asyncio.sleep(delay / 1000)
        self.records.append(RecoveryRecord(condition=rc.id, step_id=step_id, action=spec.do, attempt=n,
                                           at=datetime.now(timezone.utc)))
        self.evidence.event("recovery", condition=rc.id, step=step_id, action=spec.do, attempt=n, max=spec.max_attempts)
        if spec.do == "click":
            assert spec.target is not None
            target = self.render.render_model(spec.target)
            res = None
            for _ in range(20):
                res = await self.surface.resolve(target)
                if res.found:
                    break
                await asyncio.sleep(0.25)
            if res is None or not res.found:
                raise RecoveryExhausted(rc, n, f"recovery control not found: {target.description}")
            decision = self.guard.check(mode="replay" if self.mode != "discovery" else "discovery", action="click", el=res.brief)
            if decision.verdict != "allow":
                raise RecoveryExhausted(rc, n, f"recovery click refused by policy: {decision.reason}")
            if spec.do == "click" and delay > 250:
                await asyncio.sleep((delay - 250) / 1000)
            await self.surface.click(res)
        elif spec.do in ("dialog_accept", "dialog_dismiss"):
            await self.surface.respond_dialog(spec.do == "dialog_accept")
        elif spec.do == "reload":
            await self.surface.reload_frame([])
        await self.surface.settle(timeout_ms=10000)
