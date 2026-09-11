"""The seam between "how we perceive and act on a surface" and "the recorded flow".

Everything above this interface (the agent loop, the compiler, the replay engine, HITL)
talks in surface-agnostic terms: observations made of role/name/label/text nodes, and
`Target`s made of locators. A surface adapter implements perception, resolution, and
actions for one kind of UI. `WebSurface` (Playwright) is the one implemented here; a
desktop adapter would implement the same protocol over Windows UI Automation or the
macOS AX API, and a pixels-only adapter (Citrix/VDI) over screenshots + OCR.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..schema import Scope, Target, Text


@dataclass
class FrameObs:
    key: str  # frame name ("main") or "top"
    prefix: str  # ref prefix unique to this frame in this observation
    url: str
    title: str
    doc: str  # document instance id; a ref is only valid for the document it came from
    text: str
    nodes: list[dict[str, Any]]
    offset: tuple[int, int] = (0, 0)


@dataclass
class Observation:
    seq: int
    frames: list[FrameObs]
    dialog: dict[str, str] | None = None
    screen: str | None = None
    blocked: list[str] = field(default_factory=list)  # requests the policy aborted since the last observation

    def node(self, ref: str) -> tuple[FrameObs, dict[str, Any]] | None:
        for f in self.frames:
            if ref.startswith(f.prefix):
                for n in f.nodes:
                    if n["ref"] == ref:
                        return f, n
        return None

    def frame(self, key: str) -> FrameObs | None:
        return next((f for f in self.frames if f.key == key), None)


@dataclass
class Resolution:
    """Outcome of resolving a Target against the live surface."""

    found: bool
    handle: Any = None  # surface-specific element handle
    frame: Any = None
    locator_index: int | None = None  # which locator won (0 = primary)
    brief: dict[str, Any] | None = None  # role/name/label/text of the resolved element
    per_locator: list[int] = field(default_factory=list)  # match counts per locator
    conflict: bool = False  # two locators each matched one element, but not the same one
    reason: str = ""


class Surface(Protocol):
    async def observe(self, *, for_model: bool = False) -> Observation: ...
    async def resolve(self, target: Target) -> Resolution: ...
    async def text_visible(self, text: Text, within: list[Scope]) -> bool: ...
    async def text_snippet(self, text: Text, within: list[Scope]) -> str | None: ...
    async def url_of(self, within: list[Scope]) -> str | None: ...
    async def click(self, res: Resolution) -> None: ...
    async def fill(self, res: Resolution, value: str) -> None: ...
    async def select(self, res: Resolution, option: str) -> str: ...
    async def press(self, key: str, res: Resolution | None = None) -> None: ...
    async def respond_dialog(self, accept: bool) -> None: ...
    async def screenshot(self, path: str | None = None, *, mask: list[str] | None = None) -> bytes: ...
    async def settle(self, timeout_ms: int = 8000) -> None: ...
