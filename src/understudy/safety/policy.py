"""Policy enforcement: URL allowlist, action allowlist, and risk classification of live controls.

Enforcement happens at three layers, each catching what the one above cannot:
  1. action layer   before any action, the action type must be allowed for the mode, and the
                    live control is classified by risk (app-profile rules, then global rules);
  2. step layer     an irreversible step needs the mode's approval path (block in discovery,
                    human approval in replay);
  3. network layer  the browser aborts every request outside the origin/path allowlist, which
                    also catches javascript: navigations and redirects no element check can see.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

from ..schema import AppProfile, Policy, Risk, RiskRule, Text, TextMatch
from ..schema.target import LabelLocator, RoleLocator, TextLocator


def _norm(s: str) -> str:
    return " ".join((s or "").split()).lower()


def text_matches(actual: str, m: Text | None, default: str = "exact") -> bool:
    if m is None:
        return True
    value, mode = (m.value, m.mode) if isinstance(m, TextMatch) else (m, default)
    if mode == "exact":
        return _norm(actual) == _norm(value)
    if mode == "contains":
        return _norm(value) in _norm(actual)
    try:
        return re.search(value, " ".join((actual or "").split()), re.IGNORECASE) is not None
    except re.error:
        return False


def rule_matches(rule: RiskRule, el: dict[str, Any]) -> bool:
    loc = rule.match
    role, name, text, label = el.get("role"), el.get("name", ""), el.get("text", ""), el.get("label", "")
    if isinstance(loc, RoleLocator):
        return role == loc.role and text_matches(name, loc.name)
    if isinstance(loc, TextLocator):
        return (loc.role is None or role == loc.role) and (text_matches(text, loc.text) or text_matches(name, loc.text))
    if isinstance(loc, LabelLocator):
        return (loc.role is None or role == loc.role) and text_matches(label, loc.label)
    return False


@dataclass
class Decision:
    verdict: Literal["allow", "block", "approval"]
    risk: Risk
    reason: str


class PolicyGuard:
    def __init__(self, policy: Policy, profile: AppProfile | None = None):
        self.policy = policy
        self.profile = profile
        self._origins = {o.rstrip("/") for o in policy.allowed_origins}

    # ------------------------------------------------------------------ urls

    def url_allowed(self, url: str) -> tuple[bool, str]:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._origins:
            return False, f"origin {origin} is not in the allowlist"
        path = parts.path or "/"
        for pat in self.policy.denied_paths:
            if fnmatch.fnmatch(path, pat):
                return False, f"path {path} matches denied pattern {pat}"
        if not any(fnmatch.fnmatch(path, pat) for pat in self.policy.allowed_paths):
            return False, f"path {path} is outside the allowed paths"
        return True, ""

    # ------------------------------------------------------------------ actions

    def classify(self, el: dict[str, Any] | None, action: str) -> tuple[Risk, str]:
        """Risk of acting on a live control. Profile rules first, then global rules, else a default by action."""
        if action in ("extract", "wait"):
            return Risk.read, "read-only action"
        if el and action in ("click", "press"):
            rules = (self.profile.risk_rules if self.profile else []) + self.policy.risk_rules
            for rule in rules:
                if rule_matches(rule, el):
                    return rule.risk, rule.reason
        return Risk.reversible, "no commit rule matched"

    def check(self, *, mode: Literal["discovery", "replay"], action: str, el: dict[str, Any] | None,
              declared: Risk | None = None) -> Decision:
        mp = self.policy.discovery if mode == "discovery" else self.policy.replay
        if action not in mp.allowed_actions:
            return Decision("block", Risk.reversible, f"action '{action}' is not allowed in {mode}")
        risk, why = self.classify(el, action)
        # A reviewed artifact may not downgrade a live commit control: that means the artifact is
        # wrong or the screen changed under it. Stop rather than ask anyone to approve a surprise.
        if declared is not None and risk.rank > declared.rank:
            return Decision("block", risk, f"artifact declares this step {declared.value}, but the live control is {risk.value} ({why})")
        if declared is not None and declared.rank > risk.rank:
            risk, why = declared, "declared by the artifact"
        if risk == Risk.irreversible:
            if mp.irreversible == "block":
                return Decision("block", risk, f"irreversible action blocked in {mode}: {why}")
            if mp.irreversible == "require_approval":
                return Decision("approval", risk, why)
        return Decision("allow", risk, why)
