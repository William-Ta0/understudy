"""The compiler turns a trace into a tenant-neutral, parameterised, data-free artifact."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from understudy.compile.compiler import CompileError, Compiler
from understudy.registry import effective_profile, load_goal, load_profile, load_tenant
from understudy.safety.redact import Redactor
from understudy.schema import ClickStep, ExtractStep, FillStep, Risk, Sensitivity, Trace, TraceStep
from understudy.schema.trace import Candidate, DescribedTarget, Finish, InterventionRecord


def _c(loc: dict) -> Candidate:
    return Candidate(locator=loc, matches=1, unique=True, same=True)


def _t(frame, role, *, name="", label="", text="", cands=()) -> DescribedTarget:
    return DescribedTarget(frame=frame, role=role, name=name, label=label, text=text, candidates=[_c(c) for c in cands])


def _step(i, action, *, target=None, value=None, output=None, before=None, after=None, purpose="flow", actor="agent",
          risk=Risk.reversible, rationale="x", checkpoint=None) -> TraceStep:
    return TraceStep(index=i, actor=actor, purpose=purpose, action=action, rationale=rationale, target=target, value=value,
                     output=output, screen_before=before, screen_after=after, risk=risk, checkpoint=checkpoint,
                     at=datetime.now(timezone.utc))


def _lookup_trace(member_label: str = "Member Number", tenant: str = "lakeshore") -> Trace:
    from understudy.schema import TextCondition, TextMatch, Scope

    goal = load_goal("lookup_balance")
    steps = [
        _step(0, "click", before="workstation_home", after="member_search", rationale="Open member inquiry",
              target=_t("nav", "button", name="Member Inquiry", text="Member Inquiry",
                        cands=[{"by": "role", "role": "button", "name": "Member Inquiry"},
                               {"by": "attr", "tag": "td", "attrs": {"onclick": {"value": "mbrinq.asp", "mode": "contains"}}}])),
        _step(1, "fill", before="member_search", value="100234", rationale="Type the member number",
              target=_t("main", "textbox", label=member_label,
                        cands=[{"by": "label", "role": "textbox", "label": member_label},
                               {"by": "attr", "tag": "input", "attrs": {"name": "txtMbrNo"}},
                               {"by": "xpath", "xpath": "/html/body/form/table/tbody/tr[1]/td[2]/input"}])),
        _step(2, "click", before="member_search", after="member_detail", rationale="Search",
              target=_t("main", "button", name="Search", cands=[{"by": "role", "role": "button", "name": "Search"}])),
        _step(3, "click", before="member_detail", purpose="incidental", rationale="Dismiss a notice",
              target=_t("main", "button", name="Acknowledge", cands=[{"by": "role", "role": "button", "name": "Acknowledge"}])),
        _step(4, "checkpoint", before="member_detail", rationale="detail open",
              checkpoint=TextCondition(text=TextMatch(value="Member Detail - 100234", mode="contains"), within=[Scope(frame="main")])),
        _step(5, "extract", before="member_detail", output="member_name", risk=Risk.read,
              target=_t("main", "cell", text="DANA R WHITFIELD",
                        cands=[{"by": "label", "role": "cell", "label": "Name"}, {"by": "text", "text": "DANA R WHITFIELD"}])),
        _step(6, "extract", before="member_detail", output="savings_balance", risk=Risk.read,
              target=_t("main", "cell", cands=[{"by": "table_cell", "headers": ["Description", "Current Balance"],
                                                "row": {"Description": "Share Savings"}, "column": "Current Balance"},
                                               {"by": "xpath", "xpath": "/html/body/table[3]/tbody/tr[2]/td[4]"}])),
        _step(7, "extract", before="member_detail", output="available_balance", risk=Risk.read,
              target=_t("main", "cell", cands=[{"by": "table_cell", "headers": ["Description", "Available Balance"],
                                                "row": {"Description": "Share Savings"}, "column": "Available Balance"}])),
    ]
    return Trace(run_id="dis-test", goal=goal, tenant=tenant, product_version="7.2.4", started_at=datetime.now(timezone.utc),
                 steps=steps, finish=Finish(status="success", summary="ok", success={"kind": "screen", "screen": "member_detail"}))


def _compiler(tenant: str = "lakeshore") -> tuple[Compiler, Redactor]:
    t = load_tenant(tenant)
    r = Redactor()
    r.register("DANA R WHITFIELD", Sensitivity.pii, "member_name")
    return Compiler(effective_profile(load_profile(t.app_profile), t), t, r), r


def test_compiles_a_parameterised_tenant_neutral_artifact():
    comp, _ = _compiler()
    cap = comp.compile(_lookup_trace(), {"member_id": "100234"})
    ids = [s.id for s in cap.steps]
    assert ids == ["click_member_inquiry", "enter_member_number", "click_search", "read_member_detail"]
    fill = cap.step("enter_member_number")
    assert isinstance(fill, FillStep) and fill.value == "{{inputs.member_id}}"
    assert [loc.by for loc in fill.target.locators] == ["label", "attr"]  # positional xpath never becomes executable
    assert all(loc.why for loc in fill.target.locators)
    search = cap.step("click_search")
    assert isinstance(search, ClickStep)
    assert "Member Detail - {{inputs.member_id}}" in str(search.expect)  # checkpoint attached and parameterised
    read = cap.step("read_member_detail")
    assert isinstance(read, ExtractStep) and read.outputs == ["member_name", "savings_balance", "available_balance"]


def test_incidental_steps_become_review_notes_not_steps():
    comp, _ = _compiler()
    cap = comp.compile(_lookup_trace(), {"member_id": "100234"})
    assert not any("acknowledge" in s.id for s in cap.steps)
    assert any("situational" in n.message for n in cap.review.notes)


def test_member_data_never_reaches_the_artifact():
    comp, _ = _compiler()
    cap = comp.compile(_lookup_trace(), {"member_id": "100234"})
    text = str(cap.dump())
    assert "WHITFIELD" not in text
    assert [loc.by for loc in cap.outputs["member_name"].source.locators] == ["label"]


def test_labels_recorded_on_a_relabelled_tenant_are_stored_in_vendor_vocabulary():
    comp, _ = _compiler("pinecrest")
    cap = comp.compile(_lookup_trace(member_label="Member #", tenant="pinecrest"), {"member_id": "100234"})
    assert cap.step("enter_member_number").target.primary.label == "Member Number"


def test_human_approval_step_is_irreversible_and_gated():
    comp, _ = _compiler()
    trace = _lookup_trace()
    trace.steps.insert(3, _step(99, "click", actor="human", risk=Risk.irreversible, rationale="operator ops.jlee",
                                target=_t("main", "button", name="Confirm & Open Account",
                                          cands=[{"by": "role", "role": "button", "name": "Confirm & Open Account"}])))
    trace.interventions.append(InterventionRecord(id="int-1", kind="approval", reason="please confirm", at_step=3, human_steps=[99]))
    cap = comp.compile(trace, {"member_id": "100234"})
    step = next(s for s in cap.steps if s.origin == "human")
    assert step.risk == Risk.irreversible and step.approval == "required"
    assert "please confirm" in step.intent
    assert cap.risk == Risk.irreversible


def test_secrets_typed_by_a_human_are_never_compiled():
    comp, _ = _compiler()
    trace = _lookup_trace()
    trace.steps.insert(3, _step(98, "fill", actor="human", value="[secret]",
                                target=_t("main", "textbox", label="Override Code",
                                          cands=[{"by": "label", "role": "textbox", "label": "Override Code"}])))
    cap = comp.compile(trace, {"member_id": "100234"})
    assert not any("override" in s.id for s in cap.steps)
    assert any(n.level == "blocker" and "secret" in n.message for n in cap.review.notes)


def test_unsuccessful_discovery_does_not_compile():
    comp, _ = _compiler()
    trace = _lookup_trace()
    trace.finish = Finish(status="impossible", summary="no such member")
    with pytest.raises(CompileError):
        comp.compile(trace, {"member_id": "100234"})


def test_detours_are_pruned():
    comp, _ = _compiler()
    trace = _lookup_trace()
    home = {"top": "/default.asp", "nav": "/menu.asp", "main": "/welcome.asp"}
    wrong = _step(50, "click", before="workstation_home", after=None, rationale="Open sub-account first",
                  target=_t("nav", "button", name="Open Sub-Account", cands=[{"by": "role", "role": "button", "name": "Open Sub-Account"}]))
    wrong.frames_before, wrong.frames_after = home, {**home, "main": "/shareadd.asp"}
    first = trace.steps[0]
    first.screen_before = None
    first.frames_before, first.frames_after = {**home, "main": "/shareadd.asp"}, {**home, "main": "/mbrinq.asp"}
    trace.steps.insert(0, wrong)
    cap = comp.compile(trace, {"member_id": "100234"})
    assert cap.steps[0].id == "click_member_inquiry"
    assert any("detour" in n.message for n in cap.review.notes)


def test_select_prefers_the_option_value_when_the_label_shows_member_data():
    comp, r = _compiler()
    trace = _lookup_trace()
    r.register("$25,310.77", Sensitivity.financial)
    pick = _step(60, "select", before="member_search", value="00 - Share Savings ($25,310.77 avail)", rationale="Choose funding",
                 target=_t("main", "combobox", label="Fund From", cands=[{"by": "label", "role": "combobox", "label": "Fund From"}]))
    pick.option_value = "00"
    trace.steps.insert(2, pick)
    goal = trace.goal.model_copy(update={"inputs": {**trace.goal.inputs,
                                                     "fund_from": trace.goal.inputs["member_id"].model_copy(update={"pattern": "^[0-9]{2}$"})}})
    trace.goal = goal
    cap = comp.compile(trace, {"member_id": "100234", "fund_from": "00"})
    step = next(s for s in cap.steps if s.action == "select")
    assert step.option == "{{inputs.fund_from}}"  # the stable option value, templated; never the label with a balance
    assert "25,310" not in str(cap.dump())
