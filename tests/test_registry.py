from __future__ import annotations

from understudy.registry import effective_capability, effective_profile, load, load_profile, load_tenant
from understudy.schema import Capability, TableCellLocator

from .conftest import FIXTURES


def test_vocabulary_rewrites_display_text_for_a_tenant():
    cap = load(Capability, FIXTURES / "lookup_balance.yaml")
    eff, applied = effective_capability(cap, load_tenant("pinecrest"))
    loc = eff.outputs["savings_balance"].source.primary
    assert isinstance(loc, TableCellLocator)
    assert loc.column == "Ledger Balance" and loc.row == {"Description": "Primary Savings"}
    assert eff.step("click_member_inquiry").target.primary.name == "Member Lookup"
    assert any("Member Number -> Member #" in a for a in applied)
    # the stored artifact is untouched
    assert cap.step("click_member_inquiry").target.primary.name == "Member Inquiry"


def test_stock_tenant_changes_nothing():
    cap = load(Capability, FIXTURES / "lookup_balance.yaml")
    eff, applied = effective_capability(cap, load_tenant("lakeshore"))
    assert applied == [] and eff.content_hash() == cap.content_hash()


def test_tenant_conditions_merge_into_the_profile():
    base = load_profile("keystone-core@7")
    pine = effective_profile(base, load_tenant("pinecrest"))
    ids = [c.id for c in pine.conditions]
    assert "daily_bulletin" in ids and "daily_bulletin" not in [c.id for c in base.conditions]
    assert ids.index("daily_bulletin") < ids.index("host_timeout")  # priority order kept
    assert pine.screen("member_search").when.of[1].text == "Member Lookup"
