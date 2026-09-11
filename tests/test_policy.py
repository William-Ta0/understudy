from __future__ import annotations

import pytest

from understudy.registry import effective_profile, load_policy, load_profile, load_tenant
from understudy.safety.policy import PolicyGuard
from understudy.schema import Risk


@pytest.fixture()
def guard(mock_url: str) -> PolicyGuard:
    tenant = load_tenant("lakeshore")
    return PolicyGuard(load_policy(), effective_profile(load_profile(tenant.app_profile), tenant))


def test_url_allowlist(guard: PolicyGuard, mock_url: str):
    assert guard.url_allowed(f"{mock_url}/t/lakeshore/mbrinq.asp")[0]
    assert not guard.url_allowed(f"{mock_url}/t/lakeshore/admin/users.asp")[0]
    assert not guard.url_allowed(f"{mock_url}/t/lakeshore/signoff.asp")[0]
    assert not guard.url_allowed(f"{mock_url}/__control/reset")[0]
    assert not guard.url_allowed("https://evil.example.com/t/lakeshore/mbrinq.asp")[0]


def test_commit_controls_are_irreversible(guard: PolicyGuard):
    confirm = {"role": "button", "name": "Confirm & Open Account", "text": ""}
    assert guard.classify(confirm, "click")[0] == Risk.irreversible
    wire = {"role": "button", "name": "Send Wire", "text": "Send Wire"}  # global rule, not in the profile
    assert guard.classify({**wire, "name": "Post Transfer", "text": "Post Transfer"}, "click")[0] == Risk.irreversible
    assert guard.classify({"role": "button", "name": "Search", "text": ""}, "click")[0] == Risk.reversible
    assert guard.classify(None, "extract")[0] == Risk.read


def test_discovery_blocks_and_replay_asks(guard: PolicyGuard):
    confirm = {"role": "button", "name": "Confirm & Open Account", "text": ""}
    assert guard.check(mode="discovery", action="click", el=confirm).verdict == "block"
    assert guard.check(mode="replay", action="click", el=confirm, declared=Risk.irreversible).verdict == "approval"


def test_artifact_cannot_downgrade_a_live_commit_control(guard: PolicyGuard):
    confirm = {"role": "button", "name": "Confirm & Open Account", "text": ""}
    d = guard.check(mode="replay", action="click", el=confirm, declared=Risk.reversible)
    assert d.verdict == "block" and "live control is irreversible" in d.reason


def test_action_allowlist(guard: PolicyGuard):
    assert guard.check(mode="discovery", action="navigate", el=None).verdict == "block"
