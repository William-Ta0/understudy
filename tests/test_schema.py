"""The artifact schema enforces the rules a reviewer would otherwise have to check by hand."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from understudy.registry import load
from understudy.schema import Approval, Capability, Lifecycle, ParamSpec

from .conftest import FIXTURES


def _cap() -> Capability:
    return load(Capability, FIXTURES / "lookup_balance.yaml")


def _body() -> dict:
    return _cap().dump()


def test_fixture_loads_and_round_trips():
    cap = _cap()
    again = Capability.model_validate(cap.dump())
    assert again.content_hash() == cap.content_hash()


def test_irreversible_step_must_require_approval():
    body = _body()
    body["steps"][2]["risk"] = "irreversible"
    body["risk"] = "irreversible"
    with pytest.raises(ValidationError, match="approval: required"):
        Capability.model_validate(body)
    body["steps"][2]["approval"] = "required"
    assert Capability.model_validate(body).risk.value == "irreversible"


def test_capability_risk_must_match_riskiest_step():
    body = _body()
    body["risk"] = "read"
    with pytest.raises(ValidationError, match="riskiest step"):
        Capability.model_validate(body)


def test_outputs_may_not_use_structural_locators():
    body = _body()
    body["outputs"]["savings_balance"]["source"]["locators"] = [{"by": "css", "css": "table tr:nth-child(2) td:nth-child(4)"}]
    with pytest.raises(ValidationError, match="semantic locators"):
        Capability.model_validate(body)


def test_templates_must_reference_declared_inputs():
    body = _body()
    body["steps"][1]["value"] = "{{inputs.account_number}}"
    with pytest.raises(ValidationError, match="undeclared inputs"):
        Capability.model_validate(body)


def test_every_output_must_be_extracted():
    body = _body()
    body["steps"][3]["outputs"] = ["member_name"]
    with pytest.raises(ValidationError, match="never extracted"):
        Capability.model_validate(body)


def test_sensitive_inputs_may_not_carry_examples():
    with pytest.raises(ValidationError, match="may not carry an example"):
        ParamSpec(type="string", description="ssn", sensitivity="pii", example="912-45-6612")


def test_unknown_keys_are_rejected():
    body = _body()
    body["steps"][0]["targett"] = {}
    with pytest.raises(ValidationError):
        Capability.model_validate(body)


def test_content_hash_covers_behaviour_not_lifecycle():
    cap = _cap()
    h = cap.content_hash()
    assert cap.model_copy(update={"status": Lifecycle.approved}).content_hash() == h
    body = cap.dump()
    body["steps"][0]["intent"] = "something else"
    assert Capability.model_validate(body).content_hash() != h


def test_approval_binds_to_content_hash():
    cap = _cap()
    appr = Approval(by="reviewer", at=datetime.now(timezone.utc), content_hash=cap.content_hash())
    approved = cap.model_copy(update={"status": Lifecycle.approved, "review": cap.review.model_copy(update={"approvals": [appr]})})
    assert approved.is_approved()
    body = approved.dump()
    body["steps"][1]["value"] = "0{{inputs.member_id}}"
    edited = Capability.model_validate(body)
    assert edited.status == Lifecycle.approved and not edited.is_approved()


def test_json_schema_exports():
    schema = Capability.model_json_schema(by_alias=True)
    assert "steps" in schema["properties"] and "schema" in schema["properties"]
