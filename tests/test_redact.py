from __future__ import annotations

from understudy.safety.redact import Redactor
from understudy.schema import Sensitivity


def test_patterns_are_scrubbed():
    r = Redactor()
    s = r.text("ssn 912-45-6612 mail d.whitfield@example.com tel (906) 555-0142 card 4111 1111 1111 1111")
    assert "912-45-6612" not in s and "example.com" not in s and "555-0142" not in s and "4111" not in s
    assert "[ssn]" in s and "[email]" in s and "[phone]" in s and "[card]" in s


def test_non_luhn_digit_runs_and_ids_are_left_alone():
    assert Redactor().text("confirmation KC-20260911-0417 ref 1234567890123") == "confirmation KC-20260911-0417 ref 1234567890123"
    assert Redactor().text("run rep-20260911-140131-e9d9") == "run rep-20260911-140131-e9d9"  # Luhn-valid by accident
    assert Redactor().text("keystone.member.open_share_account@1.0.0") == "keystone.member.open_share_account@1.0.0"


def test_known_values_are_scrubbed_everywhere():
    r = Redactor()
    r.register("DANA R WHITFIELD", Sensitivity.pii, "member_name")
    r.register("2431.18", Sensitivity.financial, "savings_balance")
    r.register("100234", Sensitivity.internal, "member_id")  # internal values stay readable
    s = r.text("read DANA R WHITFIELD balance 2431.18 for 100234")
    assert s == "read [pii:member_name] balance [financial:savings_balance] for 100234"


def test_values_become_placeholders_with_stable_fingerprints():
    r = Redactor()
    a = r.value("2431.18", Sensitivity.financial)
    assert a["redacted"] == "financial" and a["fp"] == r.value("2431.18", Sensitivity.financial)["fp"]
    assert r.value("hunter2", Sensitivity.secret) == {"redacted": "secret"}
    assert r.value("Share Savings", Sensitivity.public) == "Share Savings"


def test_multi_word_values_are_caught_however_they_are_retyped():
    r = Redactor()
    r.register("DANA R WHITFIELD", Sensitivity.pii, "member_name")
    s = r.text("Dana R. Whitfield can withdraw it; so can dana whitfield; DANAR is someone else")
    assert "Whitfield" not in s and "whitfield" not in s and "DANAR" in s
