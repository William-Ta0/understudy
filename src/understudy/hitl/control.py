"""Control of a live session: who holds it, how it is handed over, and what the human did.

The model is a single-holder lease on the live surface:

    automation --escalate()--> paused --claim()--> human --release()--> automation
         |                                           ^
         +-------------- claim() (takeover) ---------+

- Exactly one holder at a time. Every transfer bumps `epoch` and is logged as evidence.
- Automation calls `checkpoint()` before every action. If a human has taken the wheel (an
  operator can grab it at any time, without being asked), the automation parks there until
  control comes back, then re-synchronises on screen state before continuing.
- While a human holds control, the page itself reports every click/input/select through
  the capture binding. It does not matter whether the operator uses the console relay or a
  headed browser window: capture is channel-independent, and nothing the automation does is
  attributed to the human (the automation is parked while they drive).
- The session is never swapped: the human works in the same browser context, cookies, and
  in-flight app state the automation was using, which is what makes resuming possible.
"""

from __future__ import annotations

import asyncio
import secrets
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal, Protocol

from ..evidence import Evidence
from ..safety.redact import Redactor
from ..schema import HumanAction, InterventionRequest, InterventionResolution, Sensitivity
from ..schema.intervention import Resolution
from ..surface.web import WebSurface


class Holder(str, Enum):
    automation = "automation"
    paused = "paused"  # automation stopped and asked for a human; nobody is driving
    human = "human"


class ControlError(RuntimeError):
    pass


class InterventionRouter(Protocol):
    def route(self, request: InterventionRequest, session: LiveSession) -> None: ...


def _now() -> datetime:
    return datetime.now(UTC)


class LiveSession:
    def __init__(self, center: ControlCenter, run_id: str, mode: Literal["discovery", "replay"], label: str,
                 surface: WebSurface, evidence: Evidence, redactor: Redactor):
        self.center = center
        self.run_id = run_id
        self.mode = mode
        self.label = label
        self.surface = surface
        self.evidence = evidence
        self.redactor = redactor
        self.holder = Holder.automation
        self.operator: str | None = None
        self.epoch = 0
        self.status = "starting"
        self.request: InterventionRequest | None = None
        self.last_resolution: InterventionResolution | None = None
        self._resolution: asyncio.Future[InterventionResolution] | None = None
        self._returned = asyncio.Event()
        self._returned.set()
        self._claimed_at: datetime | None = None
        self._actions: list[HumanAction] = []
        surface.on_capture = self._on_capture

    # ------------------------------------------------------------------ automation side

    async def checkpoint(self) -> InterventionResolution | None:
        """Call before every automated action. Returns a resolution if a human took over meanwhile."""
        if self.holder == Holder.automation:
            return None
        self.evidence.event("automation_parked", holder=self.holder.value, epoch=self.epoch)
        await self._returned.wait()
        return self.last_resolution

    async def escalate(self, *, kind: str, reason: str, context: dict[str, Any], options: list[Resolution],
                       timeout_s: float) -> InterventionResolution:
        """Pause automation, route an intervention request, and wait for a human to resolve it."""
        if self.holder != Holder.automation:
            raise ControlError(f"cannot escalate while {self.holder.value} holds control")
        shot = await self.evidence.screenshot(self.surface, f"intervention-{kind}")
        req = InterventionRequest(
            id=f"int-{secrets.token_hex(3)}",
            run_id=self.run_id,
            mode=self.mode,
            kind=kind,  # type: ignore[arg-type]
            reason=reason,
            context=self.redactor.obj(context),
            screenshot=shot,
            console_url=self.center.console_link(self.run_id),
            options=options,
            created_at=_now(),
        )
        self.request = req
        self._actions = []  # each intervention records only what happened during it
        self._transfer(Holder.paused, reason=f"escalated: {kind}")
        loop = asyncio.get_running_loop()
        self._resolution = loop.create_future()
        self._returned.clear()
        self.evidence.write_json(f"intervention-{req.id}.json", req)
        self.evidence.event("intervention_requested", id=req.id, kind=kind, reason=reason, context=req.context,
                            screenshot=shot, console=req.console_url, options=list(options))
        self.center.router.route(req, self)
        try:
            res = await asyncio.wait_for(asyncio.shield(self._resolution), timeout=timeout_s)
        except TimeoutError:
            res = self._finish(operator="system", resolution="abort", note=f"no operator resolved the request within {timeout_s:.0f}s")
            res = res.model_copy(update={"note": "ESCALATION_TIMEOUT"})
        self.request = None
        return res

    # ------------------------------------------------------------------ operator side

    def claim(self, operator: str) -> None:
        """Take control of the live session. Works on a paused session or as an unrequested takeover."""
        if self.holder == Holder.human and self.operator != operator:
            raise ControlError(f"{self.operator} already holds control")
        if self.holder == Holder.human:
            return
        self.operator = operator
        self._claimed_at = _now()
        self._actions = []
        self._returned.clear()
        self._transfer(Holder.human, reason="operator claimed control", operator=operator)

    def release(self, operator: str, resolution: Resolution, note: str | None = None) -> InterventionResolution:
        """Hand control back. From `paused` an operator may also decide without driving (approve/reject/abort)."""
        if self.holder == Holder.human and operator != self.operator:
            raise ControlError(f"{operator} does not hold control ({self.operator} does)")
        if self.holder == Holder.automation:
            raise ControlError("automation already holds control")
        allowed = self.request.options if self.request else ["resume", "abort", "completed"]
        if resolution not in allowed:
            raise ControlError(f"resolution {resolution!r} not offered here (options: {allowed})")
        return self._finish(operator=operator, resolution=resolution, note=note)

    async def relay(self, operator: str, kind: str, **kw: Any) -> None:
        """Input relayed from the operator console into the live page."""
        if self.holder != Holder.human or self.operator != operator:
            raise ControlError("take control before sending input")
        if kind == "click":
            await self.surface.click_point(float(kw["x"]), float(kw["y"]))
        elif kind == "type":
            await self.surface.type_text(str(kw["text"]))
        elif kind == "key":
            await self.surface.press(str(kw["key"]))
        elif kind == "dialog":
            self._record(HumanAction(at=_now(), kind="dialog", value="accept" if kw.get("accept") else "dismiss"))
            await self.surface.respond_dialog(bool(kw.get("accept")))
        else:
            raise ControlError(f"unknown input kind {kind!r}")

    # ------------------------------------------------------------------ internals

    def _finish(self, *, operator: str, resolution: Resolution, note: str | None) -> InterventionResolution:
        res = InterventionResolution(
            request_id=self.request.id if self.request else f"takeover-{self.epoch}",
            operator=operator,
            resolution=resolution,
            note=note,
            claimed_at=self._claimed_at,
            released_at=_now(),
            human_actions=list(self._actions),
        )
        self.last_resolution = res
        self.operator = None
        self._claimed_at = None
        self._actions = []
        self._transfer(Holder.automation, reason=f"released: {resolution}", resolution=resolution, note=note,
                       human_actions=len(res.human_actions))
        self.evidence.write_json(f"intervention-{res.request_id}-resolution.json", res)
        if self._resolution is not None and not self._resolution.done():
            self._resolution.set_result(res)
        self._returned.set()
        return res

    def _transfer(self, to: Holder, **info: Any) -> None:
        frm = self.holder
        self.holder = to
        self.epoch += 1
        self.evidence.event("control_transferred", actor="human" if to == Holder.human else "system",
                            **{"from": frm.value, "to": to.value, "epoch": self.epoch}, **info)

    def _record(self, action: HumanAction) -> None:
        self._actions.append(action)
        self.evidence.event("human_action", actor="human", operator=self.operator, action=action)

    def _on_capture(self, frame: str, payload: dict[str, Any]) -> None:
        if self.holder != Holder.human:
            return
        target = payload.get("target") or {}
        sens = target.get("sensitive")
        raw = payload.get("value")
        if payload.get("secret") or sens == "secret":
            value = "[secret]" if raw is not None or payload.get("secret") else None
        elif sens in ("pii", "financial") and raw:
            value = self.redactor.value(raw, Sensitivity(sens))
            value = f"[{sens}:{value['fp']}]"
        else:
            value = raw
        kind = payload.get("kind", "click")
        self._record(HumanAction(
            at=_now(),
            kind=kind if kind in ("click", "input", "select", "key", "submit", "navigate", "dialog") else "click",
            frame=frame,
            target={k: target.get(k) for k in ("role", "name", "label", "text", "tag", "sensitive", "candidates") if target.get(k)},
            value=value if kind != "key" else payload.get("key"),
        ))


class ControlCenter:
    """Registry of live sessions, the intervention router, and the operator console address."""

    def __init__(self, router: InterventionRouter, console_base: str | None = None):
        self.router = router
        self.console_base = console_base
        self.token = secrets.token_urlsafe(12)
        self.sessions: dict[str, LiveSession] = {}
        self.on_change: Callable[[], Awaitable[None] | None] | None = None

    def open(self, run_id: str, mode: Literal["discovery", "replay"], label: str, surface: WebSurface,
             evidence: Evidence, redactor: Redactor) -> LiveSession:
        s = LiveSession(self, run_id, mode, label, surface, evidence, redactor)
        self.sessions[run_id] = s
        return s

    def close(self, run_id: str) -> None:
        self.sessions.pop(run_id, None)

    def console_link(self, run_id: str) -> str | None:
        if not self.console_base:
            return None
        return f"{self.console_base}/sessions/{run_id}?token={self.token}"
