"""Evaluating conditions against the live surface: checkpoints, screen identification, runtime-condition scans."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from urllib.parse import urlsplit

from ..schema import (
    AllCondition,
    AnyCondition,
    AppProfile,
    Condition,
    DialogCondition,
    ElementCondition,
    NotCondition,
    RuntimeCondition,
    ScreenCondition,
    TextCondition,
    UrlCondition,
)
from ..safety.policy import text_matches
from ..surface.web import DialogPending, WebSurface
from .values import Renderer


@dataclass
class Detection:
    condition: RuntimeCondition
    message: str | None


def _path_query(url: str) -> str:
    p = urlsplit(url)
    return p.path + (f"?{p.query}" if p.query else "")


class ConditionEvaluator:
    def __init__(self, surface: WebSurface, profile: AppProfile, render: Renderer):
        self.surface = surface
        self.profile = profile
        self.render = render

    async def holds(self, c: Condition) -> bool:
        s = self.surface
        if s.pending_dialog is not None and not isinstance(c, (DialogCondition, AllCondition, AnyCondition, NotCondition)):
            return False  # nothing on the page is readable while a native dialog blocks it
        try:
            match c:
                case TextCondition():
                    return await s.text_visible(self.render.render_obj(c.text) if isinstance(c.text, str) else self.render.render_model(c.text), c.within)
                case ElementCondition():
                    res = await s.resolve(self.render.render_model(c.target))
                    return res.found if c.state == "visible" else not res.found
                case UrlCondition():
                    url = await s.url_of(c.within)
                    return url is not None and fnmatch.fnmatch(_path_query(url), self.render(c.pattern))
                case DialogCondition():
                    info = s.dialog_info
                    return info is not None and (c.message is None or text_matches(info["message"], c.message, "contains"))
                case ScreenCondition():
                    return await self.holds(self.profile.screen(c.screen).when)
                case AllCondition():
                    for x in c.of:
                        if not await self.holds(x):
                            return False
                    return True
                case AnyCondition():
                    for x in c.of:
                        if await self.holds(x):
                            return True
                    return False
                case NotCondition():
                    return not await self.holds(c.of)
        except DialogPending:
            return False
        return False

    async def current_screen(self) -> str | None:
        for sc in self.profile.screens:
            if await self.holds(sc.when):
                return sc.id
        return None

    async def detect(self, screen: str | None = None) -> Detection | None:
        """First runtime condition (by priority) that holds on the current surface."""
        for rc in self.profile.conditions:
            if rc.screens is not None and screen is not None and screen not in rc.screens:
                continue
            if rc.screens is not None and screen is None and not await self._on_any(rc.screens):
                continue
            if await self.holds(rc.when):
                return Detection(rc, await self._message(rc.when))
        return None

    async def _on_any(self, screens: list[str]) -> bool:
        for sid in screens:
            if await self.holds(self.profile.screen(sid).when):
                return True
        return False

    async def _message(self, c: Condition) -> str | None:
        """The app's own words for a condition: the text that matched, or the dialog message."""
        match c:
            case TextCondition():
                try:
                    return await self.surface.text_snippet(c.text, c.within)
                except DialogPending:
                    return None
            case DialogCondition():
                return (self.surface.dialog_info or {}).get("message")
            case AllCondition() | AnyCondition():
                for x in c.of:
                    if await self.holds(x):
                        m = await self._message(x)
                        if m:
                            return m
            case ScreenCondition():
                return await self._message(self.profile.screen(c.screen).when)
        return None

    async def describe_state(self) -> dict[str, object]:
        """What we are looking at, for failure reports: screen, frame routes, and any visible error text."""
        s = self.surface
        out: dict[str, object] = {"screen": await self.current_screen()}
        if s.pending_dialog is not None:
            out["dialog"] = dict(s.dialog_info or {})
            return out
        out["frames"] = {k: _path_query(f.url) for k, f in s.frames()}
        obs = await s.observe()
        errors = [n["text"] for f in obs.frames for n in f.nodes if n.get("emphasis") == "error"]
        if errors:
            out["error_text"] = errors[:3]
        main = obs.frame("main") or (obs.frames[0] if obs.frames else None)
        if main:
            out["heading"] = next((n["text"] for n in main.nodes if n["role"] in ("cell", "heading", "text")), None)
        return out
