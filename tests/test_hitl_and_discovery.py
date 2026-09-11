"""End to end, offline: scripted discovery -> compile -> verify, and human-in-the-loop replays.

The "model" here is the scripted stand-in and the "human" is the simulated operator, which
drives the real operator console over HTTP. The control transfer, capture, and resume are real.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from understudy.agent.llm import ScriptedLLM
from understudy.hitl.runtime import operator_console
from understudy.pipeline import discover
from understudy.replay.engine import ReplayOptions
from understudy.schema import Capability, FailureCode, Lifecycle, Risk, RunStatus
from understudy.wiring import run_replay

pytestmark = pytest.mark.browser
ROOT = Path(__file__).resolve().parent.parent
EX = ROOT / "examples"
_cache: dict[str, Capability] = {}


class Router:
    def __init__(self):
        self.requests = []

    def route(self, request, session):
        self.requests.append(request)


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


OPEN = {"member_id": "104410", "product": "Money Market Share", "nickname": "Rainy day fund", "opening_deposit": "1500",
        "fund_from": "00"}


async def _open_account_cap() -> Capability:
    if "open" not in _cache:
        async with operator_console(Router(), port=_port(), operator_script=EX / "operators" / "approve_in_discovery.yaml") as c:
            out = await discover("open_share_account", "lakeshore", OPEN, ScriptedLLM(EX / "scripted" / "open_share_account.yaml"),
                                 control=c, save=False)
        assert out.capability is not None, out.compile_error
        _cache["open"] = out.capability
    return _cache["open"]


async def test_offline_discovery_compiles_and_verifies(mock, evidence_dir):
    out = await discover("lookup_balance", "lakeshore", {"member_id": "100234"},
                         ScriptedLLM(EX / "scripted" / "lookup_balance.yaml"), save=False)
    cap = out.capability
    assert out.trace.finish.status == "success" and cap is not None
    assert cap.status == Lifecycle.verified and out.verification.status == RunStatus.succeeded
    assert cap.step("enter_member_number").value == "{{inputs.member_id}}"
    assert (Path(out.evidence_dir) / "trace.json").exists() and (Path(out.evidence_dir) / "capability.yaml").exists()


async def test_discovery_hands_the_irreversible_step_to_a_human(mock, evidence_dir):
    cap = await _open_account_cap()
    confirm = next(s for s in cap.steps if s.risk == Risk.irreversible)
    assert confirm.origin == "human" and confirm.approval == "required"
    assert confirm.target.primary.name == "Confirm & Open Account"
    assert cap.status == Lifecycle.verified  # verification stopped before the commit and never opened a second account
    assert len(mock.state()["opened"]) == 1  # the one the human opened at discovery; verification opened none


async def test_unsupervised_replay_refuses_the_irreversible_step(mock, evidence_dir):
    cap = await _open_account_cap()
    res = await run_replay(cap, "lakeshore", OPEN)
    assert res.status == RunStatus.failed and res.failure.code == FailureCode.POLICY_BLOCKED
    assert mock.state()["opened"] == []


async def test_operator_approves_and_automation_commits(mock, evidence_dir):
    cap = await _open_account_cap()
    router = Router()
    async with operator_console(router, port=_port(), operator_script=EX / "operators" / "approve_in_replay.yaml") as c:
        res = await run_replay(cap, "lakeshore", OPEN, control=c, options=ReplayOptions(supervised=True))
    assert res.status == RunStatus.succeeded, res.failure
    assert res.outputs["dividend_rate"] == "2.35%" and res.outputs["confirmation_number"].startswith("KC-")
    assert [(i.kind, i.resolution) for i in res.interventions] == [("approval", "approve")]
    assert router.requests[0].context["step"]["id"] == next(s.id for s in cap.steps if s.risk == Risk.irreversible)
    assert len(mock.state()["opened"]) == 1


async def test_supervisor_takes_over_the_live_session_and_hands_back(mock, evidence_dir):
    cap = await _open_account_cap()
    big = {**OPEN, "opening_deposit": "12000"}  # over the teller limit: the app demands a supervisor override
    async with operator_console(Router(), port=_port(), operator_script=EX / "operators" / "supervisor_override.yaml") as c:
        res = await run_replay(cap, "lakeshore", big, control=c, options=ReplayOptions(supervised=True))
    assert res.status == RunStatus.succeeded, res.failure
    kinds = [(i.kind, i.resolution, i.operator) for i in res.interventions]
    assert kinds == [("human_required", "resume", "sup.kim"), ("approval", "approve", "sup.kim")]
    assert res.interventions[0].human_actions == 3  # typed id, typed code, pressed Submit (focus clicks are not actions)
    assert res.interventions[1].human_actions == 0  # approving from the paused state is a decision, not actions
    events = (Path(res.evidence_dir) / "events.jsonl").read_text()
    assert '"[secret]"' in events and "4471" not in events  # the override code was captured as a secret, never its value


async def test_operator_rejection_is_a_business_outcome(mock, evidence_dir, tmp_path):
    cap = await _open_account_cap()
    script = tmp_path / "reject.yaml"
    script.write_text("operator: ops.jlee\nhandlers:\n  - kind: approval\n    think_s: 0.2\n"
                      "    release: {resolution: reject, note: member changed their mind}\n")
    async with operator_console(Router(), port=_port(), operator_script=script) as c:
        res = await run_replay(cap, "lakeshore", OPEN, control=c, options=ReplayOptions(supervised=True))
    assert res.status == RunStatus.business_outcome and res.outcome.code == "OPERATOR_REJECTED"
    assert mock.state()["opened"] == []


async def test_live_commit_control_cannot_be_downgraded_by_the_artifact(mock, evidence_dir):
    cap = await _open_account_cap()
    body = cap.dump()
    for s in body["steps"]:
        if s.get("risk") == "irreversible":
            s["risk"], s["approval"] = "reversible", "none"
    body["risk"] = "reversible"
    res = await run_replay(Capability.model_validate(body), "lakeshore", OPEN)
    assert res.failure.code == FailureCode.POLICY_BLOCKED and "live control is irreversible" in res.failure.message
    assert mock.state()["opened"] == []


@pytest.mark.parametrize(("inputs", "fault", "code"), [
    ({"opening_deposit": "50"}, None, "DEPOSIT_REJECTED"),
    ({"member_id": "100555", "fund_from": "00", "opening_deposit": "100"}, None, "ADDRESS_VERIFICATION_PENDING"),
    ({}, {"kind": "deny", "page": "shareadd.asp"}, "PERMISSION_DENIED"),
])
async def test_business_outcomes_on_the_write_flow(mock, evidence_dir, inputs, fault, code):
    cap = await _open_account_cap()
    if fault:
        mock.fault(tenant="lakeshore", **fault)
    res = await run_replay(cap, "lakeshore", {**OPEN, **inputs})
    assert res.status == RunStatus.business_outcome and res.outcome.code == code, (res.failure, res.outcome)
