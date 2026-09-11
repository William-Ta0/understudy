"""Discovery: an LLM-driven observe -> decide -> act loop that produces a structured trace.

The platform, not the model, handles everything it already knows about (sign-on, the
app profile's recoverable conditions, conditions that need a human). The model deals with
the unknown: finding the path to the goal. Every model action passes the same policy guard
replay uses, and is recorded with its target described and validated at that instant.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from ..hitl.control import LiveSession
from ..runtime.conditions import ConditionEvaluator
from ..runtime.recovery import Recoverer, RecoveryExhausted
from ..runtime.session import SessionManager
from ..runtime.values import Renderer, parse_output, validate_inputs
from ..schema import (
    ConditionKind,
    DescribedTarget,
    GoalSpec,
    InterventionResolution,
    Risk,
    Scope,
    TextCondition,
    TextMatch,
    Trace,
    TraceStep,
)
from ..schema.trace import Candidate, Finish, InterventionRecord, LLMUsage
from ..surface.base import Observation, Resolution
from ..surface.render import render_observation
from ..wiring import Env
from .llm import LLM, LLMError, ToolCall
from .prompt import SYSTEM_PROMPT, TOOLS

ACTION_TOOLS = {"click": "click", "click_at": "click", "fill": "fill", "select_option": "select", "press_key": "press"}


def _now() -> datetime:
    return datetime.now(UTC)


class DiscoveryAgent:
    def __init__(self, goal: GoalSpec, raw_inputs: dict[str, Any], env: Env, llm: LLM, *,
                 escalation_timeout_s: float = 900):
        self.goal = goal
        self.raw_inputs = raw_inputs
        self.env = env
        self.llm = llm
        self.surface = env.surface
        self.ev = env.evidence
        self.redactor = env.redactor
        self.guard = env.guard
        self.control: LiveSession | None = env.session
        self.escalation_timeout_s = escalation_timeout_s
        self.trace = Trace(run_id=self.ev.run_id, goal=goal, tenant=env.tenant.id, product_version=env.tenant.product_version,
                           started_at=_now(), llm=LLMUsage(model=llm.model))
        self.history: list[str] = []
        self.notices: list[str] = []
        self.extracted: dict[str, Any] = {}
        self.errors_in_a_row = 0
        self.no_tool_in_a_row = 0
        self.done = False
        self.turn = 0
        self.human_wait = 0.0

    # ------------------------------------------------------------------ main loop

    async def run(self) -> Trace:
        goal = self.goal
        inputs = validate_inputs(goal.inputs, self.raw_inputs)
        for k, v in inputs.items():
            self.redactor.register(v, goal.inputs[k].sensitivity, k)
        self.inputs = inputs
        self.render = Renderer(inputs, tenant={"base_url": self.env.tenant.base_url})
        self.evaluator = ConditionEvaluator(self.surface, self.env.profile, self.render, on_observe=self.redactor.learn)
        self.recoverer = Recoverer(self.surface, self.guard, self.ev, self.render, mode="discovery")
        self.session = SessionManager(self.surface, self.env.profile, self.env.tenant, self.evaluator, self.recoverer,
                                      self.ev, self.redactor.register)
        mp = self.guard.policy.discovery
        max_steps = min(goal.limits.max_steps, mp.max_steps)
        max_seconds = min(goal.limits.max_seconds, mp.max_seconds)
        self.ev.event("discovery_started", goal=goal.goal, capability=goal.capability, tenant=self.env.tenant.id,
                      model=self.llm.model, inputs={k: self.redactor.value(v, goal.inputs[k].sensitivity, k) for k, v in inputs.items()},
                      max_steps=max_steps)
        await self.session.sign_on()
        t0 = time.monotonic()
        try:
            while not self.done:
                if self.turn >= max_steps:
                    self._finish("limit", f"step budget of {max_steps} exhausted")
                    break
                if time.monotonic() - t0 - self.human_wait > max_seconds:
                    self._finish("limit", f"time budget of {max_seconds}s exhausted")
                    break
                if self.control:
                    took = await self.control.checkpoint()
                    if took is not None:
                        self._absorb_human(took, requested=False)
                await self.surface.settle()
                await self._platform_conditions()
                if self.done:
                    break
                await self._turn()
        except LLMError as e:
            self.ev.event("llm_error", error=str(e))
            self._finish("aborted", f"model error: {e}")
        self.trace.finished_at = _now()
        self.ev.write_json("trace.json", self.trace)
        self.ev.event("discovery_finished", status=self.trace.finish.status if self.trace.finish else None,
                      agent_steps=sum(1 for s in self.trace.steps if s.actor == "agent"),
                      human_steps=sum(1 for s in self.trace.steps if s.actor == "human"), llm=self.trace.llm)
        return self.trace

    async def _turn(self) -> None:
        self.turn += 1
        obs = await self.surface.observe()
        self.redactor.learn(obs)
        screen = await self.evaluator.current_screen()
        model_mask = {s.value for s in self.guard.policy.data.mask_for_model}
        ui_for_model = render_observation(obs, mask=model_mask)
        prompt = self._prompt(ui_for_model, screen)
        image = None
        if self.guard.policy.data.send_screenshots_to_model and obs.dialog is None:
            image = await self.surface.screenshot(mask=sorted(model_mask))
        shot = await self.ev.screenshot(self.surface, f"turn{self.turn:02d}")
        ui_ref = self.ev.ui_map(f"turn{self.turn:02d}", render_observation(obs, mask={"pii", "financial", "secret"}))
        decision = await self.llm.decide(SYSTEM_PROMPT, prompt, image, TOOLS, obs)
        usage = self.trace.llm
        assert usage is not None
        usage.calls += 1
        usage.input_tokens += decision.usage.get("input_tokens", 0)
        usage.output_tokens += decision.usage.get("output_tokens", 0)
        usage.cache_read_tokens += decision.usage.get("cache_read_tokens", 0)
        call = decision.calls[0] if decision.calls else None
        self.ev.event("llm_decision", actor="agent", turn=self.turn, screen=screen, screenshot=shot, ui_map=ui_ref,
                      said=decision.text[:600], tool=call.name if call else None, args=call.args if call else None,
                      usage=decision.usage)
        if call is None:
            self.no_tool_in_a_row += 1
            self.notices.append("You must respond with exactly one tool call.")
            if self.no_tool_in_a_row >= 2:
                await self._stuck("the model stopped calling tools")
            return
        self.no_tool_in_a_row = 0
        self._frames_before = {f.key: f.url for f in obs.frames}
        result = await self._execute(call, obs, screen, decision.text)
        self.history.append(f"{self.turn}. {self._summarize_call(call, obs)} -> {result}")
        if result.startswith(("ERROR", "BLOCKED")):
            self.errors_in_a_row += 1
            if self.errors_in_a_row >= 4:
                await self._stuck("four failed actions in a row")
        else:
            self.errors_in_a_row = 0
        await self._detect_loop()

    # ------------------------------------------------------------------ prompt

    def _prompt(self, ui_map: str, screen: str | None) -> str:
        g = self.goal
        lines = [f"GOAL: {g.goal}", "", "INPUTS (type the placeholder, never the value):"]
        for k, spec in g.inputs.items():
            shown = f'= "{self.inputs[k]}"' if not spec.sensitivity.masked and k in self.inputs else "(value hidden)"
            lines.append(f"  {{{{inputs.{k}}}}} {shown}  [{spec.type.value}] {spec.description}")
        lines.append("OUTPUTS to extract:")
        for k, o in g.outputs.items():
            mark = "done" if k in self.extracted else "pending"
            lines.append(f"  {k} [{o.type.value}, {mark}]: {o.description}")
        lines += ["", f"TURN {self.turn}. Current screen id: {screen or 'unrecognised'}.", ""]
        if self.history:
            lines.append("WHAT HAPPENED SO FAR:")
            lines += [f"  {h}" for h in self.history[-15:]]
            lines.append("")
        if self.notices:
            lines.append("NOTICES:")
            lines += [f"  - {n}" for n in self.notices]
            lines.append("")
            self.notices = []
        lines += ["CURRENT SCREEN (UI map):", ui_map]
        return "\n".join(lines)

    def _summarize_call(self, call: ToolCall, obs: Observation) -> str:
        a = call.args
        tgt = ""
        if "ref" in a:
            hit = obs.node(str(a["ref"]))
            if hit:
                n = hit[1]
                tgt = f' {n["role"]} "{n.get("label") or n.get("name") or n.get("text", "")[:40]}"'
        extra = ""
        if call.name == "fill":
            extra = f' = {a.get("value")}'
        elif call.name == "select_option":
            extra = f' = {a.get("option")}'
        elif call.name in ("extract",):
            extra = f' -> {a.get("output")}'
        elif call.name in ("checkpoint",):
            extra = f' "{a.get("text")}"'
        purpose = f' [{a["purpose"]}]' if "purpose" in a else ""
        return self.redactor.text(f"{call.name}{tgt}{extra}{purpose}")

    # ------------------------------------------------------------------ tools

    async def _execute(self, call: ToolCall, obs: Observation, screen: str | None, said: str) -> str:
        name, a = call.name, call.args
        try:
            if name in ACTION_TOOLS:
                return await self._act(name, a, screen, said)
            if name == "handle_dialog":
                return await self._dialog(a, screen)
            if name == "extract":
                return await self._extract(a, screen)
            if name == "checkpoint":
                return await self._checkpoint(a, screen)
            if name == "wait":
                secs = max(0.0, min(float(a.get("seconds", 1)), 5.0))
                await self.surface.settle(timeout_ms=int(secs * 1000) + 500)
                return f"waited {secs:.1f}s"
            if name == "request_human":
                return await self._request_human(a, screen)
            if name == "finish":
                return await self._finish_tool(a, screen)
        except LLMError:
            raise
        except Exception as e:  # tool failures go back to the model as observations, not crashes
            self.ev.event("tool_error", tool=name, error=f"{type(e).__name__}: {e}"[:300])
            return f"ERROR: {type(e).__name__}: {str(e)[:200]}"
        return f"ERROR: unknown tool {name}"

    async def _describe(self, a: dict[str, Any]) -> tuple[dict[str, Any] | None, Any]:
        if "ref" in a:
            got = await self.surface.handle_for_ref(str(a["ref"]))
            if not got:
                return None, None
            return await self.surface.describe_ref(str(a["ref"])), got[1]
        if "x" in a and "y" in a:
            d = await self.surface.describe_point(float(a["x"]), float(a["y"]))
            return d, None
        return None, None

    async def _act(self, name: str, a: dict[str, Any], screen: str | None, said: str) -> str:
        action = ACTION_TOOLS[name]
        option_value: str | None = None
        described, handle = await self._describe(a)
        if described is None and name != "press_key":
            return "ERROR: that ref is not in the current UI map (or the frame navigated since). Use a ref from the latest map."
        el = {k: described.get(k, "") for k in ("role", "name", "label", "text")} if described else None
        decision = self.guard.check(mode="discovery", action=action, el=el)
        purpose = a.get("purpose", "flow")
        intent = self.redactor.text(str(a.get("intent", "")))
        value = None
        if decision.verdict != "allow":
            self._record(action, purpose, intent, said, screen, described, None, decision.risk, ok=False,
                         error=f"blocked by policy: {decision.reason}")
            self.ev.event("policy_blocked_action", actor="agent", action=action, target=el, reason=decision.reason)
            return (f"BLOCKED by policy ({decision.reason}). You may not do this. If the goal needs it, stop here "
                    "and call request_human with kind 'approval'.")
        res = Resolution(found=True, handle=handle)
        if name == "click":
            await self.surface.click(res)
        elif name == "click_at":
            await self.surface.click_point(float(a["x"]), float(a["y"]))
        elif name == "fill":
            value = str(a.get("value", ""))
            await self.surface.fill(res, self.render(value))
        elif name == "select_option":
            value = str(a.get("option", ""))
            option_value = await self.surface.select(res, self.render(value))
        elif name == "press_key":
            value = str(a.get("key", "Enter"))
            await self.surface.press(value, res if handle is not None else None)
        await self.surface.settle()
        after = await self.evaluator.current_screen()
        sens = (described or {}).get("sensitive")
        stored = value
        if value is not None and "{{" not in value and (sens in ("pii", "financial", "secret") or self.redactor.text(value) != value):
            stored = f"[{sens or 'sensitive'}]"
        self._record(action, purpose, intent, said, screen, described, stored, decision.risk, screen_after=after,
                     option_value=option_value)
        msg = "ok"
        if after != screen:
            msg += f"; the screen is now {after or 'unrecognised'}"
        if self.surface.pending_dialog is not None:
            msg += f'; a native {self.surface.dialog_info["type"]} dialog opened: "{self.surface.dialog_info["message"]}"'
        return msg

    async def _dialog(self, a: dict[str, Any], screen: str | None) -> str:
        if self.surface.pending_dialog is None:
            return "ERROR: no dialog is open"
        message = (self.surface.dialog_info or {}).get("message", "")
        accept = bool(a.get("accept"))
        await self.surface.respond_dialog(accept)
        await self.surface.settle()
        after = await self.evaluator.current_screen()
        self._record("dialog", a.get("purpose", "flow"), str(a.get("intent", "")), "", screen, None,
                     "accept" if accept else "dismiss", Risk.reversible, screen_after=after, dialog_message=message)
        return f"dialog {'accepted' if accept else 'dismissed'}; the screen is now {after or 'unrecognised'}"

    async def _extract(self, a: dict[str, Any], screen: str | None) -> str:
        out = str(a.get("output"))
        if out not in self.goal.outputs:
            return f"ERROR: '{out}' is not a declared output ({list(self.goal.outputs)})"
        spec = self.goal.outputs[out]
        described, _ = await self._describe(a)
        if described is None:
            return "ERROR: that ref is not in the current UI map"
        raw = await self.surface.read_ref(str(a["ref"])) or {}
        text = raw.get("value") if raw.get("value") not in (None, "") else raw.get("text", "")
        try:
            value = parse_output(spec.type, text or "", spec.pattern)
        except ValueError:
            self.redactor.register(text, spec.sensitivity, out)
            return f"ERROR: the element's text is not a valid {spec.type.value}; point at the cell that shows the value itself"
        self.redactor.register(text, spec.sensitivity, out)
        self.redactor.register(str(value), spec.sensitivity, out)
        semantic = [c for c in described.get("candidates", []) if c["unique"] and c["same"]
                    and c["locator"]["by"] in ("role", "label", "text", "table_cell")]
        if not semantic:
            return "ERROR: this element can only be located by position, which is not allowed for outputs. Pick the value cell in its table."
        self.extracted[out] = value
        self.trace.extracted[out] = {"sensitivity": spec.sensitivity.value, "fingerprint": self.redactor.fingerprint(str(value))}
        self._record("extract", "flow", str(a.get("intent", "")), "", screen, described, None, Risk.read, output=out)
        shown = f"[{spec.sensitivity.value}]" if spec.sensitivity.masked else repr(value)
        return f"ok: {out} = {shown} (parsed as {spec.type.value})"

    async def _checkpoint(self, a: dict[str, Any], screen: str | None) -> str:
        template = str(a.get("text", "")).strip()
        rendered = self.render(template)
        if self.redactor.text(rendered) != rendered:
            return "ERROR: a checkpoint may not contain member data. Use a heading, label, or placeholder instead."
        frame = a.get("frame")
        cond = TextCondition(text=TextMatch(value=template, mode="contains"), within=[Scope(frame=frame)] if frame else [])
        if not await self.evaluator.holds(cond):
            return f"ERROR: checkpoint not satisfied: '{rendered}' is not visible{' in frame ' + frame if frame else ''}"
        self._record("checkpoint", "flow", str(a.get("description", "")), "", screen, None, None, Risk.read, checkpoint=cond)
        return "ok: checkpoint holds and is recorded"

    async def _request_human(self, a: dict[str, Any], screen: str | None) -> str:
        kind = str(a.get("kind", "stuck"))
        reason = self.redactor.text(str(a.get("reason", "")))
        if self.control is None:
            return "ERROR: no human operator is attached to this run. If you cannot proceed, finish with status impossible."
        visible = self._pending_outputs_on_screen()
        if kind == "approval" and visible:
            return (f"ERROR: before handing over, extract the outputs shown on this screen: {visible}. "
                    "After an irreversible step you cannot come back to it.")
        res = await self._escalate("approval" if kind == "approval" else "stuck", reason, screen)
        return self._after_human_text(res)

    def _pending_outputs_on_screen(self) -> list[str]:
        """Pending outputs whose name reads like a label on the current screen (dividend_rate ~ 'Dividend Rate:')."""
        obs = self.surface.last_observation
        if obs is None:
            return []
        texts = {" ".join(n.get("text", "").lower().replace(":", " ").split()) for f in obs.frames for n in f.nodes}
        return [o for o in self.goal.outputs if o not in self.extracted and " ".join(o.lower().split("_")) in texts]

    async def _finish_tool(self, a: dict[str, Any], screen: str | None) -> str:
        status = str(a.get("status"))
        summary = self.redactor.text(str(a.get("summary", "")))
        if status == "success":
            missing = [o for o in self.goal.outputs if o not in self.extracted]
            if missing:
                return f"ERROR: cannot finish with success: outputs not extracted yet: {missing}"
            if screen is None:
                return "ERROR: cannot finish with success on an unrecognised screen"
            cps = [s.checkpoint for s in self.trace.steps if s.checkpoint is not None and s.screen_before == screen]
            from ..schema import AllCondition, ScreenCondition

            cond = AllCondition(of=[ScreenCondition(screen=screen), *cps[-2:]]) if cps else ScreenCondition(screen=screen)
            self._finish("success", summary, cond)
        else:
            self._finish("impossible", summary)
        return f"finished: {status}"

    # ------------------------------------------------------------------ platform-handled conditions

    async def _platform_conditions(self) -> None:
        for _ in range(6):
            if self.surface.pending_dialog is not None:
                return
            screen = await self.evaluator.current_screen()
            det = await self.evaluator.detect(screen)
            if det is None:
                return
            rc = det.condition
            if rc.kind == ConditionKind.recoverable and rc.recover:
                self.ev.event("condition_detected", id=rc.id, kind=rc.kind.value, message=det.message, phase="discovery")
                try:
                    if rc.recover.do == "relogin":
                        await self.session.sign_on()
                        note = "your session expired; the platform signed on again and you are back at the home screen"
                    else:
                        await self.recoverer.recover(rc, step_id=None)
                        note = f"the platform handled a known '{rc.id}' interruption automatically ({rc.recover.do})"
                except RecoveryExhausted as e:
                    self.notices.append(f"'{rc.id}' keeps recurring: {e}")
                    return
                self.trace.platform.append({"condition": rc.id, "action": rc.recover.do, "turn": self.turn})
                self.notices.append(note)
                continue
            if rc.kind == ConditionKind.human_required:
                self.ev.event("condition_detected", id=rc.id, kind=rc.kind.value, message=det.message, phase="discovery")
                if self.control is None:
                    self.notices.append(f"'{rc.id}' needs a human ({rc.description}) but none is attached")
                    return
                res = await self._escalate("human_required", rc.description, screen, condition=rc.id)
                self.notices.append(self._after_human_text(res))
                continue
            self.notices.append(f"runtime condition '{rc.id}' ({rc.kind.value}, code {rc.code}): {self.redactor.text(det.message or rc.description)}")
            return

    # ------------------------------------------------------------------ humans

    async def _escalate(self, kind: str, reason: str, screen: str | None, **extra: Any) -> InterventionResolution:
        assert self.control is not None
        ctx = {"goal": self.goal.goal, "capability": self.goal.capability, "turn": self.turn, "screen": screen,
               "recent_actions": self.history[-5:], **extra}
        self.control.status = f"waiting for a human: {kind}"
        h0 = time.monotonic()
        res = await self.control.escalate(kind=kind, reason=reason, context=ctx, options=["resume", "completed", "abort"],
                                          timeout_s=self.escalation_timeout_s)
        self.human_wait += time.monotonic() - h0
        self.control.status = "running"
        self._absorb_human(res, requested=True, kind=kind, reason=reason)
        await self.surface.settle()
        if res.resolution == "abort":
            self._finish("aborted", f"operator aborted: {res.note or ''}")
        return res

    def _absorb_human(self, res: InterventionResolution, *, requested: bool, kind: str = "takeover", reason: str = "") -> None:
        first = len(self.trace.steps)
        for act in res.human_actions:
            t = act.target or {}
            described = DescribedTarget(
                frame=act.frame, role=t.get("role") or "unknown", name=t.get("name") or "", label=t.get("label") or "",
                text=t.get("text") or "", tag=t.get("tag") or "", sensitive=t.get("sensitive"),
                candidates=[Candidate(**c) for c in t.get("candidates") or []],
            ) if t else None
            action = {"click": "click", "input": "fill", "select": "select", "key": "press", "dialog": "dialog"}.get(act.kind, act.kind)
            risk = self.guard.classify({"role": t.get("role"), "name": t.get("name", ""), "text": t.get("text", ""),
                                        "label": t.get("label", "")}, action)[0] if t else Risk.reversible
            self.trace.steps.append(TraceStep(index=len(self.trace.steps), actor="human", purpose="flow", action=action,
                                              rationale=f"operator {res.operator}", target=described, value=act.value,
                                              risk=risk, at=act.at))
        self.trace.interventions.append(InterventionRecord(
            id=res.request_id, kind=kind, reason=reason or (res.note or ""), at_step=first, resolution=res.resolution,
            operator=res.operator, human_steps=list(range(first, len(self.trace.steps)))))

    def _after_human_text(self, res: InterventionResolution) -> str:
        acts = "; ".join(self.redactor.text(f"{h.kind} {h.target.get('role', '')} "
                                            f"\"{h.target.get('label') or h.target.get('name') or h.target.get('text', '')}\""
                                            + (f" = {h.value}" if h.value else "")) for h in res.human_actions[:8])
        return (f"a human operator handled it and handed control back (resolution: {res.resolution}"
                + (f", note: {self.redactor.text(res.note)}" if res.note else "") + f"). They did: {acts or 'nothing'}.")

    async def _stuck(self, why: str) -> None:
        self.ev.event("agent_stuck", reason=why, turn=self.turn)
        if self.control is None:
            self._finish("stuck", why)
            return
        res = await self._escalate("stuck", f"The agent appears stuck: {why}", await self.evaluator.current_screen())
        self.notices.append(self._after_human_text(res))
        self.errors_in_a_row = 0

    async def _detect_loop(self) -> None:
        acts = [s for s in self.trace.steps if s.actor == "agent" and s.action not in ("checkpoint", "extract")][-3:]
        if len(acts) == 3:
            sig = {(s.action, (s.target.name or s.target.label) if s.target else None, s.screen_before, s.screen_after) for s in acts}
            if len(sig) == 1 and acts[-1].screen_before == acts[-1].screen_after:
                await self._stuck("the same action was repeated three times without changing the screen")

    # ------------------------------------------------------------------ recording

    def _record(self, action: str, purpose: str, intent: str, said: str, screen: str | None, described: dict[str, Any] | None,
                value: str | None, risk: Risk, *, ok: bool = True, error: str | None = None, screen_after: str | None = None,
                output: str | None = None, checkpoint: Any = None, dialog_message: str | None = None,
                option_value: str | None = None) -> None:
        target = None
        if described:
            cands = [Candidate(**c) for c in described.get("candidates", [])]
            if "point" in described:
                cands.append(Candidate(locator={"by": "point", **described["point"]}, matches=1, unique=True, same=True))
            target = DescribedTarget(frame=described.get("frame"), role=described.get("role", ""), name=described.get("name", ""),
                                     label=described.get("label", ""), text=described.get("text", "")[:160],
                                     tag=described.get("tag", ""), inferred=bool(described.get("inferred")),
                                     sensitive=described.get("sensitive"), candidates=cands)
        rationale = self.redactor.text(intent + (f" | {said[:300]}" if said else ""))
        if dialog_message:
            rationale += f" | dialog: {self.redactor.text(dialog_message)}"
        step = TraceStep(index=len(self.trace.steps), actor="agent", purpose=purpose if purpose in ("flow", "incidental", "exploratory") else "flow",
                         action=action, rationale=rationale, screen_before=screen, screen_after=screen_after,
                         target=target, value=value, option_value=option_value, output=output, checkpoint=checkpoint, risk=risk, ok=ok, error=error,
                         frames_before=getattr(self, "_frames_before", {}),
                         frames_after={k: f.url for k, f in self.surface.frames()}, at=_now())
        self.trace.steps.append(step)
        self.ev.event("trace_step", actor="agent", index=step.index, action=action, purpose=step.purpose, ok=ok, error=error,
                      screen_before=screen, screen_after=screen_after,
                      target={"role": target.role, "name": target.name, "label": target.label} if target else None,
                      value=value, output=output)

    def _finish(self, status: str, summary: str, success: Any = None) -> None:
        self.trace.finish = Finish(status=status, summary=summary, success=success)  # type: ignore[arg-type]
        self.done = True
        self.ev.event("agent_finished", status=status, summary=summary)
