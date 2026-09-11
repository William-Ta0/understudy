"""Fault injection for the Keystone mock.

Tests and demos arm faults over a control endpoint (`POST /__control/faults`). Each
fault fires on the next N requests whose page name matches, then disarms. This is
how we reproduce the runtime conditions the replay engine has to handle: session
expiry, interstitial notices, transient host errors, slow responses, server errors,
and permission denials. The fault lives in the environment, not in the automation,
so the automation has to *detect* each one the way it would in production.
"""

from __future__ import annotations

import fnmatch
import threading
from dataclasses import asdict, dataclass

FAULT_KINDS = {"session_expired", "notice", "host_error", "slow", "server_error", "deny"}


@dataclass
class Fault:
    kind: str
    tenant: str | None = None
    page: str | None = None  # glob on the page name, e.g. "mbrdtl.asp"
    method: str | None = None  # "GET" / "POST" / None for either
    count: int = 1
    delay_ms: int = 0

    def matches(self, tenant: str, page: str, method: str) -> bool:
        if self.tenant and self.tenant != tenant:
            return False
        if self.method and self.method.upper() != method.upper():
            return False
        if self.kind == "notice" and method.upper() != "GET":
            return False  # an interstitial can only replace a page load
        return not self.page or fnmatch.fnmatch(page, self.page)


class FaultBoard:
    def __init__(self) -> None:
        self._faults: list[Fault] = []
        self._lock = threading.Lock()
        self.fired: list[dict] = []

    def arm(self, fault: Fault) -> None:
        if fault.kind not in FAULT_KINDS:
            raise ValueError(f"unknown fault kind {fault.kind!r}")
        with self._lock:
            self._faults.append(fault)

    def take(self, tenant: str, page: str, method: str) -> list[Fault]:
        """Consume every armed fault that matches this request."""
        hit: list[Fault] = []
        with self._lock:
            for f in list(self._faults):
                if f.matches(tenant, page, method):
                    hit.append(f)
                    f.count -= 1
                    if f.count <= 0:
                        self._faults.remove(f)
                    self.fired.append({"kind": f.kind, "tenant": tenant, "page": page, "method": method})
        return hit

    def clear(self) -> None:
        with self._lock:
            self._faults.clear()
            self.fired.clear()

    def snapshot(self) -> list[dict]:
        with self._lock:
            return [asdict(f) for f in self._faults]
