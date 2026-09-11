"""The control-transfer model: one holder at a time, epochs, capture only while a human drives."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from understudy.evidence import Evidence
from understudy.hitl.control import ControlCenter, ControlError, Holder
from understudy.safety.redact import Redactor


class FakeSurface:
    def __init__(self):
        self.on_capture = None
        self.clicks: list[tuple[float, float]] = []
        self.pending_dialog = None
        self.dialog_info = None

    async def screenshot(self, path=None, *, mask=None):
        Path(path).write_bytes(b"png") if path else None
        return b"png"

    async def click_point(self, x, y):
        self.clicks.append((x, y))

    def frames(self):
        return []


class NullRouter:
    def __init__(self):
        self.routed = []

    def route(self, request, session):
        self.routed.append(request)


@pytest.fixture()
def live(tmp_path: Path):
    router = NullRouter()
    center = ControlCenter(router, console_base="http://console")
    surface = FakeSurface()
    ev = Evidence(tmp_path, "replay", "t", Redactor())
    return center.open("run-1", "replay", "cap", surface, ev, Redactor()), surface, router


async def test_escalate_claim_release(live):
    session, surface, router = live
    task = asyncio.create_task(session.escalate(kind="human_required", reason="override", context={"step": "x"},
                                                options=["resume", "abort"], timeout_s=5))
    await asyncio.sleep(0.05)
    assert session.holder == Holder.paused and router.routed and router.routed[0].console_url.startswith("http://console")
    session.claim("sup.kim")
    assert session.holder == Holder.human
    await session.relay("sup.kim", "click", x=10, y=20)
    assert surface.clicks == [(10.0, 20.0)]
    session.release("sup.kim", "resume", "done")
    res = await task
    assert res.resolution == "resume" and res.operator == "sup.kim"
    assert session.holder == Holder.automation and session.epoch == 3


async def test_only_the_holder_can_drive_or_release(live):
    session, _, _ = live
    session.claim("a")
    with pytest.raises(ControlError):
        session.claim("b")
    with pytest.raises(ControlError):
        await session.relay("b", "click", x=1, y=1)
    with pytest.raises(ControlError):
        session.release("b", "resume")


async def test_resolution_must_be_offered(live):
    session, _, _ = live
    task = asyncio.create_task(session.escalate(kind="approval", reason="r", context={}, options=["approve", "reject"], timeout_s=5))
    await asyncio.sleep(0.05)
    with pytest.raises(ControlError):
        session.release("op", "completed")
    session.release("op", "approve")  # deciding from 'paused' without taking the wheel is allowed
    assert (await task).resolution == "approve"


async def test_unrequested_takeover_parks_automation(live):
    session, _, _ = live
    session.claim("op")
    parked = asyncio.create_task(session.checkpoint())
    await asyncio.sleep(0.05)
    assert not parked.done()
    session.release("op", "resume")
    res = await parked
    assert res is not None and res.resolution == "resume"
    assert await session.checkpoint() is None  # automation holds control again


async def test_capture_records_human_actions_and_redacts_secrets(live):
    session, surface, _ = live
    surface.on_capture("main", {"kind": "click", "target": {"role": "button", "name": "Search"}})
    assert session._actions == []  # nothing is attributed to a human while automation holds control
    session.claim("op")
    surface.on_capture("main", {"kind": "input", "secret": True, "value": None, "target": {"role": "textbox", "label": "Override Code"}})
    surface.on_capture("main", {"kind": "input", "value": "DANA", "target": {"role": "textbox", "label": "Name", "sensitive": "pii"}})
    res = session.release("op", "resume")
    values = [a.value for a in res.human_actions]
    assert values[0] == "[secret]" and values[1].startswith("[pii:hmac:") and "DANA" not in str(values)


async def test_escalation_times_out(live):
    session, _, _ = live
    res = await session.escalate(kind="stuck", reason="r", context={}, options=["resume", "abort"], timeout_s=0.1)
    assert res.resolution == "abort" and res.note == "ESCALATION_TIMEOUT"
