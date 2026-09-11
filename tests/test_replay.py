"""Deterministic replay against the live mock: outcomes, recoveries, hard failures, tenants, drift, policy."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from understudy.registry import load
from understudy.schema import Capability, FailureCode, RunStatus
from understudy.wiring import run_replay

from .conftest import FIXTURES

pytestmark = pytest.mark.browser


def cap() -> Capability:
    return load(Capability, FIXTURES / "lookup_balance.yaml")


async def replay(capability: Capability, member: str = "100234", tenant: str = "lakeshore", **kw):
    return await run_replay(capability, tenant, {"member_id": member}, **kw)


async def test_success_returns_typed_outputs_and_persists_only_placeholders(mock, evidence_dir):
    res = await replay(cap())
    assert res.status == RunStatus.succeeded
    assert res.outputs == {"member_name": "DANA R WHITFIELD", "savings_balance": "2431.18", "available_balance": "2406.18"}
    persisted = json.loads((Path(res.evidence_dir) / "result.json").read_text())
    assert persisted["outputs"]["savings_balance"]["redacted"] == "financial"
    assert "2431.18" not in (Path(res.evidence_dir) / "events.jsonl").read_text()


@pytest.mark.parametrize(("member", "code"), [("999999", "MEMBER_NOT_FOUND"), ("100777", "MEMBER_RESTRICTED")])
async def test_business_outcomes_are_not_failures(mock, member, code):
    res = await replay(cap(), member)
    assert res.status == RunStatus.business_outcome and res.outcome.code == code and res.failure is None
    assert res.outcome.message  # the app's own words


async def test_invalid_input_is_rejected_before_touching_the_ui(mock):
    res = await replay(cap(), "12ab")
    assert res.status == RunStatus.failed and res.failure.code == FailureCode.INVALID_INPUT
    assert res.steps == []


@pytest.mark.parametrize(("fault", "condition"), [
    ({"kind": "notice", "page": "mbrdtl.asp"}, "system_notice"),
    ({"kind": "host_error", "page": "mbrdtl.asp"}, "host_timeout"),
    ({"kind": "host_error", "page": "mbrinq.asp", "method": "POST"}, "host_timeout"),
    ({"kind": "session_expired", "page": "mbrinq.asp", "method": "POST"}, "session_expired"),
])
async def test_recoverable_conditions_are_handled(mock, fault, condition):
    mock.fault(tenant="lakeshore", **fault)
    res = await replay(cap())
    assert res.status == RunStatus.succeeded, res.failure
    assert [r.condition for r in res.recoveries] == [condition]


async def test_slow_loads_are_waited_for(mock):
    mock.fault(tenant="lakeshore", kind="slow", page="mbrdtl.asp", delay_ms=3000)
    res = await replay(cap())
    assert res.status == RunStatus.succeeded and res.duration_ms > 3000


async def test_app_error_is_a_hard_failure_with_evidence(mock):
    mock.fault(tenant="lakeshore", kind="server_error", page="mbrdtl.asp")
    res = await replay(cap())
    assert res.status == RunStatus.failed and res.failure.code == FailureCode.APP_ERROR
    assert res.failure.step_id == "click_search" and res.failure.retryable
    assert (Path(res.evidence_dir) / res.failure.evidence["screenshot"]).exists()
    assert "ui_map" in res.failure.evidence


async def test_recurring_transient_error_exhausts_recovery(mock):
    mock.fault(tenant="lakeshore", kind="host_error", page="mbrdtl.asp", count=5)
    res = await replay(cap())
    assert res.failure.code == FailureCode.RECOVERY_EXHAUSTED and len(res.recoveries) == 2


async def test_second_tenant_via_vocabulary_and_tenant_conditions(mock):
    res = await replay(cap(), tenant="pinecrest")
    assert res.status == RunStatus.succeeded, res.failure
    assert res.outputs["savings_balance"] == "2431.18"
    assert any(w.kind == "override_applied" for w in res.warnings)
    bulletin = [r for r in res.recoveries if r.condition == "daily_bulletin"]
    assert bulletin and bulletin[0].step_id == "sign_on"  # a tenant-only interstitial, handled at sign-on and reported


async def test_primary_locator_miss_is_reported_as_drift(mock):
    body = cap().dump()
    body["steps"][1]["target"]["locators"][0]["label"] = "Member No."  # the vendor relabelled; the field name did not change
    res = await replay(Capability.model_validate(body))
    assert res.status == RunStatus.succeeded
    drift = [w for w in res.warnings if w.kind == "locator_drift"]
    assert drift and drift[0].step_id == "enter_member_number" and "attr" in drift[0].message


async def test_output_without_a_match_fails_loudly_instead_of_guessing(mock):
    body = cap().dump()
    body["outputs"]["savings_balance"]["source"]["locators"][0]["column"] = "Ledger Balance"
    body["outputs"]["savings_balance"]["source"]["locators"][0]["headers"] = ["Description", "Ledger Balance"]
    body["steps"][3]["timeout_ms"] = 2000
    res = await replay(Capability.model_validate(body))
    assert res.failure.code == FailureCode.TARGET_NOT_FOUND and "savings_balance" in res.failure.message
