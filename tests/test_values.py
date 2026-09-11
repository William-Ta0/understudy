from __future__ import annotations

import pytest

from understudy.runtime.values import InputError, Renderer, parse_output, validate_inputs
from understudy.schema import ParamSpec, ValueType


def test_inputs_are_validated_and_canonicalised():
    specs = {
        "member_id": ParamSpec(type="string", description="", pattern=r"^\d{4,10}$"),
        "deposit": ParamSpec(type="money", description="", minimum=0, sensitivity="financial"),
        "product": ParamSpec(type="enum", description="", enum=["Share Savings", "Money Market Share"]),
    }
    got = validate_inputs(specs, {"member_id": "100234", "deposit": "$1,500", "product": "money market share"})
    assert got == {"member_id": "100234", "deposit": "1500.00", "product": "Money Market Share"}


def test_bad_inputs_are_reported_per_field():
    specs = {"member_id": ParamSpec(type="string", description="", pattern=r"^\d{4,10}$"),
             "deposit": ParamSpec(type="money", description="", minimum=0)}
    with pytest.raises(InputError) as e:
        validate_inputs(specs, {"member_id": "12ab", "deposit": "-5", "extra": "x"})
    assert set(e.value.problems) == {"member_id", "deposit", "extra"}


def test_missing_required_input():
    with pytest.raises(InputError, match="required"):
        validate_inputs({"member_id": ParamSpec(type="string", description="")}, {})


def test_output_parsing():
    assert parse_output(ValueType.money, "$2,431.18") == "2431.18"
    assert parse_output(ValueType.money, "($12.00)") == "-12.00"
    assert parse_output(ValueType.date, "04/18/2011") == "2011-04-18"
    assert parse_output(ValueType.string, "  DANA  R WHITFIELD ") == "DANA R WHITFIELD"
    with pytest.raises(ValueError):
        parse_output(ValueType.money, "n/a")


def test_renderer_refuses_unknown_templates():
    r = Renderer(inputs={"member_id": "1"})
    assert r("Member Detail - {{inputs.member_id}}") == "Member Detail - 1"
    with pytest.raises(KeyError):
        r("{{inputs.nope}}")
