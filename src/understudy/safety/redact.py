"""Redaction for everything we persist: event logs, evidence, traces, and the text the model sees.

Two mechanisms, applied together:
  - known values: every input/output/secret with a masked sensitivity is registered for the run
    and scrubbed wherever it appears, whatever the surrounding format;
  - patterns: SSNs, card numbers, emails, phone numbers, long account-like digit runs.

Values are replaced by a typed placeholder, and optionally by a keyed fingerprint (HMAC),
so two runs can be compared for "same output" without either run storing the value.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets as _secrets
from pathlib import Path
from typing import Any

from ..schema import Sensitivity

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("card", re.compile(r"\b(?:\d{4}[ -]){3}\d{1,7}\b|\b\d{13,19}\b")),  # grouped in fours, or one unbroken run
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}\b")),  # alphabetic TLD: "cap@1.0.0" is a version
    ("phone", re.compile(r"\(\d{3}\)\s?\d{3}-\d{4}|\b\d{3}-\d{3}-\d{4}\b")),
    ("amount", re.compile(r"\$\s?-?[\d,]+\.\d{2}")),  # any displayed dollar amount: balances hide in option labels and messages
]


def _luhn_ok(digits: str) -> bool:
    ds = [int(c) for c in digits if c.isdigit()]
    if not 13 <= len(ds) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(ds)):
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _fingerprint_key() -> bytes:
    env = os.environ.get("UNDERSTUDY_FINGERPRINT_KEY")
    if env:
        return env.encode()
    path = Path(os.environ.get("UNDERSTUDY_STATE_DIR", ".understudy")) / "fingerprint.key"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_secrets.token_hex(32))
        path.chmod(0o600)
    return path.read_text().strip().encode()


class Redactor:
    def __init__(self) -> None:
        self._known: dict[str, str] = {}  # raw value -> placeholder
        self._fuzzy: dict[str, re.Pattern[str]] = {}  # multi-word values, matched however they are re-typed
        self._key = _fingerprint_key()

    def fingerprint(self, value: str) -> str:
        return "hmac:" + hmac.new(self._key, value.encode(), hashlib.sha256).hexdigest()[:16]

    def register(self, value: str | None, kind: Sensitivity | str, label: str | None = None) -> None:
        """Scrub this exact value from everything persisted for the rest of the run."""
        if value is None:
            return
        v = str(value).strip()
        if len(v) < 2:
            return
        k = kind.value if isinstance(kind, Sensitivity) else kind
        if k in ("public", "internal"):
            return
        self._known[v] = f"[{k}:{label}]" if label else f"[{k}]"
        words = re.findall(r"[A-Za-z0-9]+", v)
        if len(words) >= 2 and any(len(w) > 2 for w in words):
            # "DANA R WHITFIELD" must also catch "Dana R. Whitfield" and "Dana Whitfield" in model-written text.
            sep = r"[\s.,'-]+"
            full = sep.join(map(re.escape, words))
            core = [w for w in words if len(w) > 2]
            alt = sep.join(map(re.escape, core)) if len(core) >= 2 and core != words else None
            rx = rf"(?<![A-Za-z0-9])(?:{full}{'|' + alt if alt else ''})(?![A-Za-z0-9])"
            self._fuzzy[v] = re.compile(rx, re.IGNORECASE)

    def learn(self, observation: Any) -> None:
        """Register every value the page itself marked sensitive, so it is scrubbed wherever it shows up later."""
        for f in getattr(observation, "frames", []):
            for n in f.nodes:
                kind = n.get("sensitive")
                if kind in ("pii", "financial", "secret"):
                    for v in (n.get("text"), n.get("value")):
                        if v and len(str(v).strip()) >= 4 and not str(v).startswith("*"):
                            self.register(v, kind)

    def text(self, s: str) -> str:
        if not s:
            return s
        for raw in sorted(self._known, key=len, reverse=True):
            if raw in s:
                s = s.replace(raw, self._known[raw])
            elif raw in self._fuzzy:
                s = self._fuzzy[raw].sub(self._known[raw], s)
        for kind, rx in PATTERNS:
            if kind == "card":
                s = rx.sub(lambda m: "[card]" if _luhn_ok(m.group(0)) else m.group(0), s)
            else:
                s = rx.sub(f"[{kind}]", s)
        return s

    def value(self, value: Any, sensitivity: Sensitivity, label: str | None = None) -> Any:
        """Placeholder + fingerprint for a masked value; the value itself otherwise (still pattern-scrubbed)."""
        if sensitivity.masked:
            return {"redacted": sensitivity.value, "fp": self.fingerprint(str(value))} if sensitivity != Sensitivity.secret else {"redacted": "secret"}
        return self.obj(value)

    def obj(self, x: Any) -> Any:
        if isinstance(x, str):
            return self.text(x)
        if isinstance(x, dict):
            return {k: self.obj(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [self.obj(v) for v in x]
        return x
