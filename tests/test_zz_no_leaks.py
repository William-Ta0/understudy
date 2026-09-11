"""Nothing sensitive may reach disk: scan every evidence file and artifact for the mock's synthetic PII.

Runs last (file name), over the committed evidence/ and capabilities/ trees plus everything this
test session wrote under pytest's temp directory.
"""

from __future__ import annotations

import os
from pathlib import Path

from keystone_mock.data import SEED_MEMBERS, SUPERVISORS, USERS, money

ROOT = Path(__file__).resolve().parent.parent


def _needles() -> set[str]:
    out: set[str] = set()
    for m in SEED_MEMBERS.values():
        out |= {m.display_name, f"{m.first} {m.middle} {m.last}", f"{m.first} {m.middle}. {m.last}", f"{m.first} {m.last}",
                m.ssn, m.dob, m.address, m.phone, m.email}
        for a in m.accounts:
            if a.current > 100:
                out |= {money(a.current), money(a.available)}
    out |= {u["password"] for u in USERS.values()} | set(SUPERVISORS.values())
    return {n for n in out if len(n) >= 4}


def _files(extra: Path) -> list[Path]:
    roots = [ROOT / "evidence", ROOT / "capabilities", extra, Path(os.environ.get("UNDERSTUDY_EVIDENCE_DIR", ROOT / "evidence"))]
    files = []
    for r in roots:
        if r.exists():
            files += [p for p in r.rglob("*") if p.is_file() and p.suffix in (".json", ".jsonl", ".yaml", ".txt", ".md")]
    return files


def test_no_synthetic_pii_or_secrets_on_disk(tmp_path_factory):
    needles = _needles()
    leaks = []
    for f in _files(tmp_path_factory.getbasetemp()):
        text = f.read_text(errors="ignore").lower()
        leaks += [(str(f.relative_to(f.anchor)), n) for n in needles if n.lower() in text]
    assert not leaks, f"sensitive values found on disk: {leaks[:10]}"
