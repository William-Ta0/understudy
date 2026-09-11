"""Deterministic replay: run a capability with typed inputs, no model in the loop.

Per step:

    1. checkpoint()   park if a human has taken control; re-sync on screen state when they hand back
    2. settle         network quiet, frames loaded (bounded)
    3. scan           runtime conditions from the app profile, by priority:
                        recoverable     -> handle it (bounded attempts), rescan
                        business        -> stop, return the mapped business outcome
                        fatal           -> stop, hard failure with evidence
                        human_required  -> escalate on the live session, wait, re-sync
    4. precondition   the step's screen must be showing (bounded wait, scanning while waiting)
    5. resolve        the target's locators in order; exactly one visible match; primary-miss = drift
    6. policy         action allowlist + live risk classification; irreversible -> human approval
    7. act
    8. checkpoint     wait for `expect` while scanning, so a "no such member" banner resolves in
                      milliseconds as a business outcome instead of timing out as a failure

Anything the engine cannot explain becomes a hard failure (or, when running supervised,
an escalation) carrying the step, what was expected, what was observed, and evidence.
"""

from __future__ import annotations

import asyncio
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..evidence import Evidence
from ..hitl.control import LiveSession
from ..runtime.conditions import ConditionEvaluator, Detection
from ..runtime.recovery import RecoveryExhausted, Recoverer
from ..runtime.session import LoginError, SessionManager
from ..runtime.values import InputError, Renderer, parse_output, validate_inputs
from ..safety.policy import PolicyGuard
from ..safety.redact import Redactor
from ..schema import (
    AppProfile,
    BusinessOutcome,
    Capability,
    CheckStep,
    ClickStep,
    Condition,
    ConditionKind,
    DialogStep,
    ExtractStep,
    Failure,
    FailureCode,
    FillStep,
    InterventionResolution,
    InterventionSummary,
    PressStep,
    Risk,
    RunResult,
    RunStatus,
    SelectStep,
    Step,
    StepRecord,
    TenantBinding,
    WaitStep,
    Warning,
    describe_locator,
    summarize,
)
from ..schema.result import RETRYABLE
from ..surface.base import Resolution
from ..surface.render import render_observation
from ..surface.web import WebSurface


@dataclass
class ReplayOptions:
    supervised: bool = False  # escalate to a human instead of failing when stuck
    require_approved: bool = False  # production: refuse capabilities that are not approved
    escalation_timeout_s: float = 900
    max_restarts: int = 1
    stop_before_irreversible: bool = False  # verification mode: prove the flow up to the commit point, never commit


class _Outcome(Exception):
    def __init__(self, outcome: BusinessOutcome):
        self.outcome = outcome


class _Fail(Exception):
    def __init__(self, failure: Failure):
        self.failure = failure


class _Stuck(Exception):
    """A hard failure a human might be able to fix. Escalated when supervised, failed otherwise."""

    def __init__(self, failure: Failure):
        self.failure = failure


class _Restart(Exception):
    pass


class _HumanCompleted(Exception):
    pass


class _StopBeforeCommit(Exception):
    def __init__(self, step_id: str):
        self.step_id = step_id


class ReplayEngine:
    def __init__(self, cap: Capability, profile: AppProfile, tenant: TenantBinding, guard: PolicyGuard,
                 surface: WebSurface, evidence: Evidence, redactor: Redactor, control: LiveSession | None,
                 options: ReplayOptions, overrides: list[str] | None = None):
        self.cap = cap
        self.profile = profile
        self.tenant = tenant
        self.guard = guard
        self.surface = surface
        self.ev = evidence
        self.redactor = redactor
        self.control = control
        self.opt = options
        self.overrides = overrides or []
        self.render = Renderer(tenant={"base_url": tenant.base_url})
        self.evaluator = ConditionEvaluator(surface, profile, self.render, on_observe=redactor.learn)
        self.recoverer = Recoverer(surface, guard, evidence, self.render)
        self.session = SessionManager(surface, profile, tenant, self.evaluator, self.recoverer, evidence, redactor.register)
        self.outputs: dict[str, Any] = {}
        self.warnings: list[Warning] = []
        self.records: list[StepRecord] = []
        self.interventions: list[InterventionSummary] = []
        self.irreversible_done = False
        self._human_wait = 0.0
        self._step: tuple[int, Step] | None = None

    # ------------------------------------------------------------------ entry point

    async def run(self, raw_inputs: dict[str, Any]) -> RunResult:
        started = datetime.now(timezone.utc)
        t0 = time.monotonic()
        cap = self.cap
        status, outcome, failure = RunStatus.failed, None, None
        self.ev.event("run_started", capability=cap.id, version=cap.version, content_hash=cap.content_hash(),
                      lifecycle=cap.status.value, tenant=self.tenant.id, product_version=self.tenant.product_version,
                      inputs={k: (self.redactor.value(v, cap.inputs[k].sensitivity, k) if k in cap.inputs else "?")
                              for k, v in raw_inputs.items()},
                      overrides=self.overrides, supervised=self.opt.supervised)
        for o in self.overrides:
            self.warnings.append(Warning(kind="override_applied", message=o))
        try:
            inputs = self._validate(raw_inputs)
            self.render.scopes["inputs"] = inputs
            if self.opt.require_approved and not cap.is_approved():
                raise _Fail(Failure(code=FailureCode.NOT_APPROVED,
                                    message=f"{cap.id}@{cap.version} is {cap.status.value}; unattended runs need an approved capability"))
            await self._sign_on()
            restarts = 0
            while True:
                try:
                    await self._run_steps()
                    break
                except _Restart:
                    restarts += 1
                    if restarts > self.opt.max_restarts:
                        raise _Fail(Failure(code=FailureCode.RECOVERY_EXHAUSTED, message="session kept expiring", retryable=True))
                    self.ev.event("flow_restarted", reason="session re-established", restart=restarts)
            await self._verify_success()
            status = RunStatus.succeeded
        except _StopBeforeCommit as s:
            status = RunStatus.succeeded
            self.warnings.append(Warning(kind="verification_stop", step_id=s.step_id,
                                         message=f"stopped before irreversible step '{s.step_id}' (verification mode); target resolved"))
        except _Outcome as o:
            status, outcome = RunStatus.business_outcome, o.outcome
        except _Fail as f:
            failure = f.failure
        except Exception as e:  # engine bug or infrastructure fault: still a structured, debuggable result
            failure = Failure(code=FailureCode.INTERNAL_ERROR, message=f"{type(e).__name__}: {e}",
                              details={"traceback": traceback.format_exc()[-2000:]})
        finished = datetime.now(timezone.utc)
        if failure is not None:
            failure = failure.model_copy(update={"retryable": failure.retryable or failure.code in RETRYABLE})
        result = RunResult(
            run_id=self.ev.run_id,
            capability={"id": cap.id, "version": cap.version, "content_hash": cap.content_hash()},
            tenant=self.tenant.id,
            status=status,
            outputs=self.outputs if status == RunStatus.succeeded else None,
            outcome=outcome,
            failure=failure,
            recoveries=self.recoverer.records,
            warnings=self.warnings,
            interventions=self.interventions,
            steps=self.records,
            started_at=started,
            finished_at=finished,
            duration_ms=int((time.monotonic() - t0) * 1000),
            evidence_dir=str(self.ev.dir),
        )
        persisted = self._redacted(result)
        self.ev.write_json("result.json", persisted, redact=False)
        self.ev.event("run_finished", status=status.value, outcome=outcome.code if outcome else None,
                      failure=failure.code.value if failure else None, duration_ms=result.duration_ms)
        return result

    def _redacted(self, result: RunResult) -> RunResult:
        """The persisted copy: masked outputs become placeholders + fingerprints."""
        outs = None
        if result.outputs is not None:
            outs = {k: self.redactor.value(v, self.cap.outputs[k].sensitivity, k) for k, v in result.outputs.items()}
        return RunResult.model_validate(self.redactor.obj({**result.dump(), "outputs": outs}))

    def _validate(self, raw: dict[str, Any]) -> dict[str, str]:
        try:
            inputs = validate_inputs(self.cap.inputs, raw)
        except InputError as e:
            self.ev.event("input_rejected", problems=e.problems)
            raise _Fail(Failure(code=FailureCode.INVALID_INPUT, message="inputs do not satisfy the capability contract",
                                expected="see capability inputs", observed=str(e), details={"problems": e.problems})) from None
        for k, v in inputs.items():
            self.redactor.register(v, self.cap.inputs[k].sensitivity, k)
        return inputs

    async def _sign_on(self) -> None:
        try:
            await self.session.sign_on()
        except LoginError as e:
            raise _Fail(await self._failure(FailureCode.LOGIN_FAILED, str(e), None, retryable=True)) from None

    # ------------------------------------------------------------------ steps

    async def _run_steps(self) -> None:
        steps = self.cap.steps
        i = 0
        self.irreversible_done = False
        while i < len(steps):
            step = steps[i]
            self._step = (i, step)
            self._check_budget()
            if self.control:
                took = await self.control.checkpoint()
                if took is not None:
                    i = await self._after_human(took, i)
                    continue
            t0 = time.monotonic()
            self.ev.event("step_started", step=step.id, index=i, action=step.action, intent=step.intent)
            try:
                locator = await self._run_step(i, step)
            except _Stuck as s:
                if not self.opt.supervised or self.control is None:
                    raise _Fail(s.failure) from None
                res = await self._escalate("stuck", s.failure.message, step, extra={"failure": s.failure.code.value,
                                                                                    "expected": s.failure.expected})
                i = await self._after_human(res, i)
                continue
            except _HumanCompleted:
                await self._finish_after_human(i)
                return
            ms = int((time.monotonic() - t0) * 1000)
            self.records.append(StepRecord(id=step.id, status="done", duration_ms=ms, locator=locator))
            self.ev.event("step_completed", step=step.id, index=i, duration_ms=ms)
            if ms > step.timeout_ms * 0.8:
                self.warnings.append(Warning(kind="slow_step", step_id=step.id, message=f"{ms} ms (timeout {step.timeout_ms} ms)"))
            i += 1

    def _check_budget(self) -> None:
        elapsed = time.monotonic() - self.ev._t0 - self._human_wait
        if elapsed > self.guard.policy.replay.max_seconds:
            raise _Fail(Failure(code=FailureCode.TIMEOUT, message=f"run exceeded {self.guard.policy.replay.max_seconds}s",
                                step_id=self._step[1].id if self._step else None))

    async def _run_step(self, i: int, step: Step) -> str | None:
        deadline = time.monotonic() + step.timeout_ms / 1000
        await self.surface.settle(timeout_ms=step.timeout_ms)
        await self._scan(step)
        if step.screen:
            await self._await(self._screen_cond(step.screen), step, deadline, FailureCode.UNEXPECTED_SCREEN,
                              f"expected screen '{step.screen}' before acting")
        if isinstance(step, ExtractStep):
            for name in step.outputs:
                await self._extract(step, name, deadline)
            return None
        if isinstance(step, WaitStep):
            await self._await(step.until, step, deadline, FailureCode.CHECKPOINT_FAILED, step.intent)
            return None
        if isinstance(step, DialogStep):
            await self._await_dialog(step, deadline)
            return None
        assert isinstance(step, (ClickStep, FillStep, SelectStep, CheckStep, PressStep))
        res = await self._resolve(step, deadline) if step.target is not None else None
        locator = describe_locator(step.target.locators[res.locator_index]) if res and res.found else None
        decision = self.guard.check(mode="replay", action=step.action, el=res.brief if res else None, declared=step.risk)
        self.ev.event("policy_decision", step=step.id, verdict=decision.verdict, risk=decision.risk.value, reason=decision.reason)
        performed_by_human = False
        if decision.verdict == "block":
            raise _Fail(await self._failure(FailureCode.POLICY_BLOCKED, decision.reason, step))
        if (decision.verdict == "approval" or step.approval == "required") and self.opt.stop_before_irreversible:
            self.ev.event("stopped_before_irreversible", step=step.id, locator=locator)
            raise _StopBeforeCommit(step.id)
        if decision.verdict == "approval" or step.approval == "required":
            performed_by_human = await self._approve(step)
            if not performed_by_human:
                res = await self._resolve(step, time.monotonic() + step.timeout_ms / 1000)  # the page may have moved on
        if not performed_by_human:
            await self._perform(step, res)
        if step.risk == Risk.irreversible:
            self.irreversible_done = True
        if step.expect is not None:
            await self._await(step.expect, step, time.monotonic() + step.timeout_ms / 1000, FailureCode.CHECKPOINT_FAILED,
                              f"checkpoint after '{step.id}'")
        return locator

    async def _perform(self, step: Step, res: Resolution | None) -> None:
        detail: dict[str, Any] = {"step": step.id, "action": step.action}
        if isinstance(step, ClickStep):
            await self.surface.click(res)
        elif isinstance(step, FillStep):
            value = self.render(step.value)
            await self.surface.fill(res, value)
            detail["value"] = value
        elif isinstance(step, SelectStep):
            option = self.render(step.option)
            option = self.tenant.vocabulary.get(option, option)  # enum values are in vendor vocabulary
            try:
                await self.surface.select(res, option)
            except LookupError as e:
                raise _Fail(await self._failure(FailureCode.TARGET_NOT_FOUND, str(e), step, expected=f"option '{option}'")) from None
            detail["option"] = option
        elif isinstance(step, CheckStep):
            await self.surface.check(res, step.checked)
        elif isinstance(step, PressStep):
            await self.surface.press(step.key, res)
            detail["key"] = step.key
        self.ev.event("action_performed", **detail)
        await self.surface.settle(timeout_ms=step.timeout_ms)

    # ------------------------------------------------------------------ waiting, scanning, resolving

    def _screen_cond(self, screen: str) -> Condition:
        from ..schema import ScreenCondition

        return ScreenCondition(screen=screen)

    async def _await(self, cond: Condition, step: Step | None, deadline: float, code: FailureCode, what: str) -> None:
        """Wait for `cond`, handling runtime conditions as they appear. Checks the target state first."""
        while True:
            if await self.evaluator.holds(cond):
                return
            if await self._scan(step):
                continue
            if time.monotonic() > deadline:
                raise _Stuck(await self._failure(code, f"{what}: condition not met in time", step, expected=summarize(cond)))
            await asyncio.sleep(0.2)

    async def _scan(self, step: Step | None) -> bool:
        """Detect and respond to one runtime condition. Returns True if something was handled."""
        sid = step.id if step else None
        if self.surface.pending_dialog is not None:
            det = await self.evaluator.detect()
            if det is None or det.condition.when.kind != "dialog":
                info = dict(self.surface.dialog_info or {})
                await self.surface.respond_dialog(accept=False)
                raise _Stuck(await self._failure(FailureCode.UNEXPECTED_DIALOG, f"unexpected {info.get('type')} dialog",
                                                 step, observed=info.get("message")))
        else:
            screen = await self.evaluator.current_screen()
            det = await self.evaluator.detect(screen)
        if det is None:
            return False
        rc = det.condition
        self.ev.event("condition_detected", step=sid, id=rc.id, kind=rc.kind.value, message=det.message)
        if rc.kind == ConditionKind.recoverable:
            assert rc.recover is not None
            if rc.recover.do == "relogin":
                if self.irreversible_done:
                    raise _Fail(await self._failure(FailureCode.RECOVERY_EXHAUSTED,
                                                    "session expired after an irreversible step; refusing to replay it", step))
                try:
                    self.recoverer.attempts[rc.id] += 1
                    if self.recoverer.attempts[rc.id] > rc.recover.max_attempts + self.opt.max_restarts:
                        raise RecoveryExhausted(rc, self.recoverer.attempts[rc.id] - 1)
                    self.recoverer.records.append(_record(rc.id, sid, "relogin", self.recoverer.attempts[rc.id]))
                    self.ev.event("recovery", condition=rc.id, step=sid, action="relogin", attempt=self.recoverer.attempts[rc.id])
                    await self.session.sign_on()
                except (LoginError, RecoveryExhausted) as e:
                    raise _Fail(await self._failure(FailureCode.RECOVERY_EXHAUSTED, str(e), step, retryable=True)) from None
                raise _Restart()
            try:
                await self.recoverer.recover(rc, sid)
            except RecoveryExhausted as e:
                raise _Fail(await self._failure(FailureCode.RECOVERY_EXHAUSTED, str(e), step, observed=det.message,
                                                retryable=True)) from None
            return True
        if rc.kind == ConditionKind.business:
            raise _Outcome(await self._business(det, step))
        if rc.kind == ConditionKind.fatal:
            raise _Fail(await self._failure(FailureCode.APP_ERROR, f"{rc.id}: {rc.description}", step,
                                            observed=det.message, details={"condition": rc.id, "code": rc.code}))
        # human_required
        if self.control is None:
            raise _Fail(await self._failure(FailureCode.ESCALATION_TIMEOUT,
                                            f"{rc.id} needs a human and no operator channel is attached", step))
        res = await self._escalate("human_required", rc.description, step, extra={"condition": rc.id})
        if res.resolution == "abort":
            raise _Fail(await self._failure(_abort_code(res), f"operator aborted at {rc.id}: {res.note or ''}", step))
        if res.resolution == "completed":
            raise _HumanCompleted()
        return True

    async def _business(self, det: Detection, step: Step | None) -> BusinessOutcome:
        rc = det.condition
        if rc.recover and rc.recover.do in ("dialog_accept", "dialog_dismiss"):  # leave the app clean before returning
            await self.surface.respond_dialog(rc.recover.do == "dialog_accept")
        spec = next((o for o in self.cap.outcomes if o.condition == rc.id), None)
        shot = await self.ev.screenshot(self.surface, f"outcome-{rc.id}")
        out = BusinessOutcome(
            code=spec.code if spec else (rc.code or rc.id.upper()),
            description=spec.description if spec else rc.description,
            condition=rc.id,
            message=self.redactor.text(det.message) if det.message else None,
            step_id=step.id if step else None,
            retryable=spec.retryable if spec else False,
        )
        self.ev.event("business_outcome", code=out.code, condition=rc.id, step=out.step_id, message=out.message,
                      declared=spec is not None, screenshot=shot)
        return out

    async def _resolve(self, step: ClickStep | FillStep | SelectStep | CheckStep | PressStep, deadline: float) -> Resolution:
        target = self.render.render_model(step.target)
        while True:
            res = await self.surface.resolve(target)
            if res.found:
                self._note_resolution(step.id, target, res, risky=step.risk == Risk.irreversible)
                return res
            if await self._scan(step):
                continue
            if time.monotonic() > deadline:
                raise _Stuck(await self._failure(
                    FailureCode.TARGET_NOT_FOUND, f"could not find {target.description}", step,
                    expected="; ".join(describe_locator(loc) for loc in target.locators),
                    details={"matches_per_locator": res.per_locator}))
            await asyncio.sleep(0.25)

    def _note_resolution(self, where: str, target: Any, res: Resolution, *, risky: bool) -> None:
        if res.conflict:
            msg = f"locators disagree on {target.description}; using locator #{res.locator_index}"
            self.warnings.append(Warning(kind="ambiguity", step_id=where, message=msg, details={"matches": res.per_locator}))
            self.ev.event("locator_conflict", step=where, matches=res.per_locator)
            if risky:
                raise _Fail(Failure(code=FailureCode.TARGET_AMBIGUOUS, message=msg + " on an irreversible step", step_id=where))
        if res.locator_index:
            primary = describe_locator(target.locators[0])
            used = describe_locator(target.locators[res.locator_index])
            self.warnings.append(Warning(kind="locator_drift", step_id=where,
                                         message=f"primary locator missed ({primary}); resolved by fallback #{res.locator_index} ({used})",
                                         details={"primary": primary, "used": used, "matches": res.per_locator}))
            self.ev.event("locator_drift", step=where, primary=primary, used=used, matches=res.per_locator)

    async def _extract(self, step: ExtractStep, name: str, deadline: float) -> None:
        spec = self.cap.outputs[name]
        target = self.render.render_model(spec.source)
        while True:
            res = await self.surface.resolve(target)
            if res.found:
                break
            if await self._scan(step):
                continue
            if time.monotonic() > deadline:
                raise _Stuck(await self._failure(
                    FailureCode.TARGET_NOT_FOUND, f"could not find output '{name}' ({target.description})", step,
                    expected="; ".join(describe_locator(loc) for loc in target.locators),
                    details={"output": name, "matches_per_locator": res.per_locator}))
            await asyncio.sleep(0.25)
        self._note_resolution(f"{step.id}:{name}", target, res, risky=True)
        raw = await self.surface.read(res) or {}
        text = raw.get("value") if spec.read == "value" else raw.get("text")
        try:
            value = parse_output(spec.type, text or "", spec.pattern)
        except ValueError as e:
            self.redactor.register(text, spec.sensitivity, name)
            raise _Fail(await self._failure(FailureCode.OUTPUT_INVALID, f"output '{name}' is not a valid {spec.type.value}",
                                            step, observed=self.redactor.text(str(e)))) from None
        self.redactor.register(text, spec.sensitivity, name)
        self.redactor.register(str(value), spec.sensitivity, name)
        self.outputs[name] = value
        self.ev.event("output_extracted", step=step.id, output=name, value_type=spec.type.value,
                      value=self.redactor.value(value, spec.sensitivity, name),
                      locator=describe_locator(target.locators[res.locator_index or 0]))

    async def _await_dialog(self, step: DialogStep, deadline: float) -> None:
        while self.surface.pending_dialog is None:
            if time.monotonic() > deadline:
                raise _Stuck(await self._failure(FailureCode.CHECKPOINT_FAILED, "expected a dialog that never appeared", step))
            await asyncio.sleep(0.1)
        await self.surface.respond_dialog(step.response == "accept")
        self.ev.event("action_performed", step=step.id, action="dialog", response=step.response)

    async def _verify_success(self) -> None:
        deadline = time.monotonic() + 5
        while not await self.evaluator.holds(self.cap.success):
            if time.monotonic() > deadline:
                raise _Fail(await self._failure(FailureCode.CHECKPOINT_FAILED, "success condition not met at end of flow", None,
                                                expected=summarize(self.cap.success)))
            await asyncio.sleep(0.2)
        missing = [k for k, o in self.cap.outputs.items() if o.required and k not in self.outputs]
        if missing:
            raise _Fail(Failure(code=FailureCode.OUTPUT_INVALID, message=f"required outputs missing: {missing}"))
        shot = await self.ev.screenshot(self.surface, "success")
        self.ev.event("checkpoint_passed", checkpoint="success", condition=summarize(self.cap.success), screenshot=shot)

    # ------------------------------------------------------------------ human in the loop

    async def _approve(self, step: Step) -> bool:
        """Irreversible step gate. Returns True if the human performed the step themselves."""
        mp = self.guard.policy.replay
        if mp.irreversible == "block":
            raise _Fail(await self._failure(FailureCode.POLICY_BLOCKED, "irreversible steps are blocked by policy", step))
        if self.control is None:
            raise _Fail(await self._failure(FailureCode.POLICY_BLOCKED,
                                            f"step '{step.id}' is irreversible and needs a human approval; run with --supervised", step))
        res = await self._escalate("approval", f"Approval needed: {step.intent}", step, options=["approve", "reject", "completed", "abort"])
        if res.resolution == "approve":
            self.ev.event("approval_granted", step=step.id, operator=res.operator)
            return False
        if res.resolution == "completed":
            self.ev.event("step_performed_by_human", step=step.id, operator=res.operator, actions=len(res.human_actions))
            return True
        if res.resolution == "reject":
            raise _Outcome(BusinessOutcome(code="OPERATOR_REJECTED", description="A human operator declined the irreversible step.",
                                           condition="approval", message=res.note, step_id=step.id))
        raise _Fail(await self._failure(_abort_code(res), f"operator aborted at approval: {res.note or ''}", step))

    async def _escalate(self, kind: str, reason: str, step: Step | None, *, extra: dict[str, Any] | None = None,
                        options: list[str] | None = None) -> InterventionResolution:
        assert self.control is not None
        ctx = {
            "capability": f"{self.cap.id}@{self.cap.version}",
            "tenant": self.tenant.id,
            "step": {"id": step.id, "intent": step.intent, "index": self._step[0] if self._step else None} if step else None,
            "screen": await self.evaluator.current_screen(),
            "frames": {k: f.url for k, f in self.surface.frames()},
            **(extra or {}),
        }
        self.control.status = f"waiting for a human: {kind}"
        t0 = time.monotonic()
        res = await self.control.escalate(kind=kind, reason=reason, context=ctx,
                                          options=options or ["resume", "completed", "abort"],  # type: ignore[arg-type]
                                          timeout_s=self.opt.escalation_timeout_s)
        self._human_wait += time.monotonic() - t0
        self.interventions.append(InterventionSummary(id=res.request_id, kind=kind, reason=reason,
                                                      step_id=step.id if step else None, resolution=res.resolution,
                                                      operator=res.operator, human_actions=len(res.human_actions)))
        self.control.status = "running"
        await self.surface.settle()
        return res

    async def _after_human(self, res: InterventionResolution, i: int) -> int:
        """Re-synchronise after a human handed control back. Returns the step index to continue from."""
        if res.resolution == "abort":
            raise _Fail(await self._failure(_abort_code(res), f"operator aborted: {res.note or ''}", self.cap.steps[i]))
        if res.resolution == "completed":
            await self._finish_after_human(i)
            return len(self.cap.steps)
        screen = await self.evaluator.current_screen()
        steps = self.cap.steps
        target = i
        if steps[i].screen and steps[i].screen != screen:
            later = next((j for j in range(i + 1, len(steps)) if steps[j].screen == screen), None)
            if later is not None:
                for j in range(i, later):
                    self.records.append(StepRecord(id=steps[j].id, status="by_human", duration_ms=0))
                target = later
        self.ev.event("resynced", screen=screen, resume_at=steps[target].id if target < len(steps) else None,
                      skipped=[s.id for s in steps[i:target]])
        return target

    async def _finish_after_human(self, i: int) -> None:
        """The operator says the task is done: run only the remaining read-only steps, then verify success."""
        for j in range(i, len(self.cap.steps)):
            s = self.cap.steps[j]
            if isinstance(s, ExtractStep):
                for name in s.outputs:
                    await self._extract(s, name, time.monotonic() + s.timeout_ms / 1000)
                self.records.append(StepRecord(id=s.id, status="done", duration_ms=0))
            else:
                self.records.append(StepRecord(id=s.id, status="by_human", duration_ms=0))

    # ------------------------------------------------------------------ failures

    async def _failure(self, code: FailureCode, message: str, step: Step | None, *, expected: str | None = None,
                       observed: str | None = None, retryable: bool = False, details: dict[str, Any] | None = None) -> Failure:
        """Build a failure with evidence: masked screenshot, redacted UI map, and a summary of what was on screen."""
        evidence: dict[str, str] = {}
        state: dict[str, Any] = {}
        try:
            state = await self.evaluator.describe_state()
            shot = await self.ev.screenshot(self.surface, f"failure-{code.value.lower()}")
            if shot:
                evidence["screenshot"] = shot
            if self.surface.pending_dialog is None:
                obs = await self.surface.observe()
                self.redactor.learn(obs)
                evidence["ui_map"] = self.ev.ui_map("failure", render_observation(obs, mask={"pii", "financial", "secret"}))
        except Exception as e:  # evidence capture must never mask the original failure
            state["evidence_error"] = str(e)[:200]
        obs_text = observed or ""
        if state:
            obs_text = (obs_text + " | " if obs_text else "") + f"screen={state.get('screen')}, frames={state.get('frames')}" + (
                f", error_text={state.get('error_text')}" if state.get("error_text") else "")
        f = Failure(code=code, message=self.redactor.text(message), step_id=step.id if step else None,
                    step_index=self._step[0] if self._step and step else None, expected=expected,
                    observed=self.redactor.text(obs_text) or None, retryable=retryable, evidence=evidence,
                    details=self.redactor.obj({**(details or {}), "state": state}))
        self.ev.event("failure", code=code.value, step=f.step_id, message=f.message, expected=expected, observed=f.observed,
                      evidence=evidence)
        return f


def _abort_code(res: InterventionResolution) -> FailureCode:
    return FailureCode.ESCALATION_TIMEOUT if res.note == "ESCALATION_TIMEOUT" else FailureCode.HUMAN_ABORTED


def _record(cond: str, step: str | None, action: str, attempt: int):
    from ..schema import RecoveryRecord

    return RecoveryRecord(condition=cond, step_id=step, action=action, attempt=attempt, at=datetime.now(timezone.utc))
