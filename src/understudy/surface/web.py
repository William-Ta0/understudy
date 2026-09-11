"""Web surface adapter over Playwright (Chromium).

Perception and resolution run in-page (perceive.js, injected into every frame), so this
adapter is mostly plumbing: frames, element handles, native dialogs, network allowlist
enforcement, settling, and masked screenshots.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from playwright.async_api import (
    Browser,
    BrowserContext,
    Dialog,
    ElementHandle,
    Frame,
    Page,
    Playwright,
    Route,
    async_playwright,
)
from playwright.async_api import Error as PlaywrightError

from ..schema import Scope, Target, Text, TextMatch
from .base import FrameObs, Observation, Resolution

log = logging.getLogger(__name__)

_HERE = Path(__file__).parent
PERCEIVE_JS = (_HERE / "perceive.js").read_text()
CAPTURE_JS = (_HERE.parent / "hitl" / "capture.js").read_text()

UrlGuard = Callable[[str], tuple[bool, str]]


class DialogPending(RuntimeError):
    """A native dialog is blocking the page; JS cannot run until someone answers it."""


def _tm(text: Text, default_mode: str) -> dict[str, str]:
    if isinstance(text, TextMatch):
        return text.dump()
    return {"value": text, "mode": default_mode}


class WebSurface:
    def __init__(self, pw: Playwright, browser: Browser, context: BrowserContext, page: Page, url_guard: UrlGuard | None):
        self._pw = pw
        self.browser = browser
        self.context = context
        self.page = page
        self.url_guard = url_guard
        self.pending_dialog: Dialog | None = None
        self.dialog_info: dict[str, str] | None = None
        self._inflight: asyncio.Task | None = None
        self._net_inflight = 0
        self._last_net = time.monotonic()
        self._req_seq = 0
        self._act_seq: int | None = None
        self._act_at = 0.0
        self._blocked: list[str] = []
        self._obs_seq = 0
        self._prefixes: dict[str, str] = {}
        self.last_observation: Observation | None = None
        self.on_blocked: Callable[[str, str], None] | None = None
        self.on_capture: Callable[[str, dict[str, Any]], Awaitable[None] | None] | None = None
        self.on_dialog: Callable[[dict[str, str]], None] | None = None

    # ------------------------------------------------------------------ lifecycle

    @classmethod
    async def launch(
        cls,
        *,
        headless: bool = True,
        url_guard: UrlGuard | None = None,
        viewport: tuple[int, int] = (1280, 800),
        slow_mo_ms: int = 0,
    ) -> WebSurface:
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=headless, slow_mo=slow_mo_ms)
        context = await browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]},
            locale="en-US",
            timezone_id="America/Detroit",
            accept_downloads=False,
            service_workers="block",
        )
        page = await context.new_page()
        self = cls(pw, browser, context, page, url_guard)
        await context.add_init_script(PERCEIVE_JS)
        await context.add_init_script(CAPTURE_JS)
        await context.expose_binding("__us_capture", self._capture_binding)
        await context.route("**/*", self._route)
        page.on("dialog", self._on_dialog)
        page.on("request", self._on_request)
        page.on("requestfinished", self._on_request_done)
        page.on("requestfailed", self._on_request_done)
        return self

    async def close(self) -> None:
        try:
            await self.context.close()
            await self.browser.close()
        finally:
            await self._pw.stop()

    # ------------------------------------------------------------------ events

    def _on_dialog(self, dialog: Dialog) -> None:
        # Hold the dialog open. Whoever is in control (replay, model, human) decides how to answer.
        self.pending_dialog = dialog
        self.dialog_info = {"type": dialog.type, "message": dialog.message}
        if self.on_dialog:
            self.on_dialog(dict(self.dialog_info))

    def _on_request(self, _req: Any) -> None:
        self._net_inflight += 1
        self._req_seq += 1
        self._last_net = time.monotonic()

    def _on_request_done(self, _req: Any) -> None:
        self._net_inflight = max(0, self._net_inflight - 1)
        self._last_net = time.monotonic()

    async def _route(self, route: Route) -> None:
        url = route.request.url
        if url.startswith(("data:", "blob:", "about:")):
            await route.continue_()
            return
        if url.rstrip("/").endswith("/favicon.ico"):
            await route.abort()
            return
        ok, reason = self.url_guard(url) if self.url_guard else (True, "")
        if ok:
            await route.continue_()
            return
        # Network-level enforcement: catches javascript: navigations and redirects that no element check can see.
        self._blocked.append(url)
        if self.on_blocked:
            self.on_blocked(url, reason)
        await route.abort("blockedbyclient")

    async def _capture_binding(self, source: dict[str, Any], payload: dict[str, Any]) -> None:
        if not self.on_capture:
            return
        frame: Frame | None = source.get("frame")
        key = self._frame_key(frame) if frame else "top"
        r = self.on_capture(key, payload)
        if asyncio.iscoroutine(r):
            await r

    # ------------------------------------------------------------------ frames

    def _frame_key(self, frame: Frame) -> str:
        if frame == self.page.main_frame:
            return "top"
        if frame.name:
            return frame.name
        return f"frame{self.page.frames.index(frame)}"

    def frames(self) -> list[tuple[str, Frame]]:
        return [(self._frame_key(f), f) for f in self.page.frames if not f.is_detached()]

    def frames_for(self, within: list[Scope]) -> list[Frame]:
        chain = [s.frame for s in within if s.frame is not None]
        if not chain:
            return [f for _, f in self.frames()]
        current: Frame = self.page.main_frame
        for name in chain:
            # child_frames keeps detached frames from earlier documents around; skip them.
            nxt = next((c for c in current.child_frames if c.name == name and not c.is_detached()), None)
            if nxt is None:
                nxt = next((f for f in self.page.frames if f.name == name and not f.is_detached()), None)
            if nxt is None or nxt.is_detached():
                return []
            current = nxt
        return [current]

    def _prefix(self, key: str) -> str:
        if key not in self._prefixes:
            base = "t" if key == "top" else key[0].lower()
            p, n = base, 1
            while p in self._prefixes.values():
                n += 1
                p = f"{base}{n}_"
            self._prefixes[key] = p
        return self._prefixes[key]

    async def _eval(self, frame: Frame, expr: str, arg: Any = None) -> Any:
        if self.pending_dialog:
            raise DialogPending(self.dialog_info["message"] if self.dialog_info else "")
        try:
            if not await frame.evaluate("() => !!(window.__us && window.__us.version === 4)"):
                await frame.evaluate(PERCEIVE_JS)
            return await frame.evaluate(expr, arg)
        except PlaywrightError as e:
            # Frames detach and contexts are destroyed mid-navigation; callers treat this as "not there yet".
            log.debug("evaluate failed in %s: %s", frame.url, e)
            return None

    # ------------------------------------------------------------------ perception

    async def observe(self, *, record: bool = True) -> Observation:
        """Snapshot every frame. `record=False` (operator console) leaves the automation's view untouched."""
        self._obs_seq += 1
        blocked = self._blocked if record else []
        if record:
            self._blocked = []
        if self.pending_dialog:
            obs = Observation(seq=self._obs_seq, frames=[], dialog=dict(self.dialog_info or {}), blocked=blocked)
            if record:
                self.last_observation = obs
            return obs
        frames: list[FrameObs] = []
        for key, fr in self.frames():
            prefix = self._prefix(key)
            snap = await self._eval(fr, "o => window.__us.snapshot(o)", {"prefix": prefix})
            if not snap:
                continue
            offset = (0, 0)
            if fr != self.page.main_frame:
                try:
                    el = await fr.frame_element()
                    bb = await el.bounding_box()
                    if bb:
                        offset = (round(bb["x"]), round(bb["y"]))
                except PlaywrightError:
                    pass
            frames.append(FrameObs(key=key, prefix=prefix, url=snap["url"], title=snap["title"], doc=snap["doc"],
                                   text=snap["text"], nodes=snap["nodes"], offset=offset))
        obs = Observation(seq=self._obs_seq, frames=frames, blocked=blocked)
        if record:
            self.last_observation = obs
        return obs

    async def text_visible(self, text: Text, within: list[Scope]) -> bool:
        js_scopes = [s.dump() for s in within if s.dialog is not None]
        for fr in self.frames_for(within):
            if await self._eval(fr, "([m, w]) => window.__us.textVisible(m, w)", [_tm(text, "contains"), js_scopes]):
                return True
        return False

    async def text_snippet(self, text: Text, within: list[Scope]) -> str | None:
        js_scopes = [s.dump() for s in within if s.dialog is not None]
        for fr in self.frames_for(within):
            s = await self._eval(fr, "([m, w]) => window.__us.textSnippet(m, w)", [_tm(text, "contains"), js_scopes])
            if s:
                return s
        return None

    async def url_of(self, within: list[Scope]) -> str | None:
        if not any(s.frame for s in within):
            return self.page.url
        frames = self.frames_for(within)
        return frames[0].url if frames else None

    async def resolve(self, target: Target) -> Resolution:
        frames = self.frames_for(target.within)
        if not frames:
            return Resolution(found=False, reason=f"scope {[str(s) for s in target.within]} not present")
        js_scopes = [s.dump() for s in target.within if s.dialog is not None]
        per: list[int] = []
        uniques: list[tuple[int, Frame, dict[str, Any]]] = []
        for idx, loc in enumerate(target.locators):
            total, hits = 0, []
            for fr in frames:
                res = await self._eval(fr, "([l, w]) => window.__us.resolve(l, w)", [loc.dump(), js_scopes])
                for r in res or []:
                    if "more" in r:
                        total += r["more"]
                    else:
                        total += 1
                        hits.append((fr, r))
            per.append(total)
            if total == 1:
                uniques.append((idx, hits[0][0], hits[0][1]))
        if not uniques:
            return Resolution(found=False, per_locator=per, reason=f"no locator matched exactly one visible element (matches per locator: {per})")
        idx, fr, brief = uniques[0]
        conflict = any(f is not fr or b["ref"] != brief["ref"] for _, f, b in uniques[1:])
        handle = await fr.evaluate_handle("r => window.__us.refs.get(r)", brief["ref"])
        el = handle.as_element()
        if el is None:
            return Resolution(found=False, per_locator=per, reason="element vanished during resolution")
        return Resolution(found=True, handle=el, frame=fr, locator_index=idx, brief=brief, per_locator=per, conflict=conflict)

    async def handle_for_ref(self, ref: str) -> tuple[Frame, ElementHandle] | None:
        """Element handle for a ref from the latest observation. Rejects refs whose document has since changed."""
        obs = self.last_observation
        hit = obs.node(ref) if obs else None
        if not hit:
            return None
        fobs, _ = hit
        frames = dict(self.frames())
        fr = frames.get(fobs.key)
        if fr is None:
            return None
        doc = await self._eval(fr, "() => window.__us.doc")
        if doc != fobs.doc:
            return None
        handle = await fr.evaluate_handle("r => window.__us.refs.get(r)", ref)
        el = handle.as_element()
        return (fr, el) if el else None

    async def describe_ref(self, ref: str) -> dict[str, Any] | None:
        got = await self.handle_for_ref(ref)
        if not got:
            return None
        fr, _ = got
        d = await self._eval(fr, "r => window.__us.describe(r, [])", ref)
        if d:
            d["frame"] = self._frame_key(fr)
        return d

    async def describe_point(self, x: float, y: float) -> dict[str, Any] | None:
        """Describe whatever element is under a page coordinate (coordinate fallback for the agent)."""
        for key, fr in reversed(self.frames()):
            ox, oy = 0.0, 0.0
            if fr != self.page.main_frame:
                try:
                    bb = await (await fr.frame_element()).bounding_box()
                except PlaywrightError:
                    continue
                if not bb or not (bb["x"] <= x < bb["x"] + bb["width"] and bb["y"] <= y < bb["y"] + bb["height"]):
                    continue
                ox, oy = bb["x"], bb["y"]
            d = await self._eval(fr, "([x, y]) => { const el = document.elementFromPoint(x, y); "
                                     "return el ? window.__us.describeEl(el) : null; }", [x - ox, y - oy])
            if d:
                d["frame"] = key
                d["point"] = {"x": round(x - ox), "y": round(y - oy)}
                return d
        return None

    async def read_ref(self, ref: str) -> dict[str, Any] | None:
        got = await self.handle_for_ref(ref)
        if not got:
            return None
        fr, _ = got
        return await self._eval(fr, "r => window.__us.readRef(r)", ref)

    async def read(self, res: Resolution) -> dict[str, Any] | None:
        return await res.handle.evaluate(
            """el => ({text: (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim(),
                       value: ('value' in el && el.tagName !== 'BUTTON') ? (el.tagName === 'SELECT'
                              ? (el.options[el.selectedIndex] || {text: ''}).text : el.value) : null})"""
        )

    # ------------------------------------------------------------------ actions

    async def _act(self, fn: Callable[[], Awaitable[Any]]) -> None:
        """Run an action; return early if it opens a native dialog (the action stalls until someone answers)."""
        self._act_seq, self._act_at = self._req_seq, time.monotonic()
        task = asyncio.ensure_future(fn())
        self._inflight = task
        while True:
            done, _ = await asyncio.wait({task}, timeout=0.05)
            if task in done:
                self._inflight = None
                task.result()
                return
            if self.pending_dialog:
                return

    async def click(self, res: Resolution) -> None:
        await self._act(lambda: res.handle.click(timeout=5000))

    async def fill(self, res: Resolution, value: str) -> None:
        await self._act(lambda: res.handle.fill(value, timeout=5000))

    async def select(self, res: Resolution, option: str) -> str:
        opts: list[list[str]] = await res.handle.evaluate("el => Array.from(el.options).map(o => [o.text.trim(), o.value])")
        m = re.match(r'^"?(.*?)"?\s*(?:\[value=([^\]]*)\]|\(=([^)]*)\))\s*$', option.strip())
        if m:  # the UI map's own notation was copied back: '"Label" [value=X]'
            label, val = m.group(1), m.group(2) or m.group(3)
            option = label if any(" ".join(t.split()).lower() == " ".join(label.split()).lower() for t, _ in opts) else val
        want = " ".join(option.split()).lower()
        norm = lambda t: " ".join(t.split()).lower()  # noqa: E731
        # Exact visible label, then exact option value, then a unique label that starts with the text ("00 - ...").
        match = next((v for t, v in opts if norm(t) == want), None)
        if match is None:
            match = next((v for t, v in opts if v.lower() == want), None)
        if match is None:
            pref = [v for t, v in opts if norm(t).startswith(want + " ")]
            match = pref[0] if len(pref) == 1 else None
        if match is None:
            raise LookupError(f"no option {option!r}; available: {[t for t, _ in opts]}")
        await self._act(lambda: res.handle.select_option(value=match, timeout=5000))
        return match

    async def check(self, res: Resolution, checked: bool) -> None:
        await self._act(lambda: res.handle.set_checked(checked, timeout=5000))

    async def press(self, key: str, res: Resolution | None = None) -> None:
        if res is not None:
            await self._act(lambda: res.handle.press(key, timeout=5000))
        else:
            await self._act(lambda: self.page.keyboard.press(key))

    async def click_point(self, x: float, y: float) -> None:
        await self._act(lambda: self.page.mouse.click(x, y))

    async def type_text(self, text: str) -> None:
        await self._act(lambda: self.page.keyboard.type(text, delay=15))

    async def respond_dialog(self, accept: bool) -> None:
        dialog = self.pending_dialog
        if dialog is None:
            return
        self.pending_dialog = None
        self.dialog_info = None
        try:
            await (dialog.accept() if accept else dialog.dismiss())
        except PlaywrightError:
            pass
        if self._inflight is not None:
            try:
                await asyncio.wait_for(self._inflight, timeout=10)
            except (TimeoutError, PlaywrightError):
                pass
            self._inflight = None

    async def goto(self, url: str) -> None:
        await self.page.goto(url, wait_until="load")

    async def reload_frame(self, within: list[Scope]) -> None:
        frames = self.frames_for(within)
        if frames and frames[0] != self.page.main_frame:
            await self._eval(frames[0], "() => location.reload()")
        else:
            await self.page.reload()

    # ------------------------------------------------------------------ settle & screenshots

    async def settle(self, timeout_ms: int = 8000, quiet_ms: int = 250, grace_ms: int = 400) -> None:
        """Wait until the network is quiet and every frame has finished loading, bounded by timeout.

        Right after an action, a navigation may not have *started* yet (a click runs a script that
        submits a form a tick later). So first give it `grace_ms` to issue a request.
        """
        deadline = time.monotonic() + timeout_ms / 1000
        if self._act_seq is not None:
            while self._req_seq == self._act_seq and (time.monotonic() - self._act_at) * 1000 < grace_ms:
                if self.pending_dialog:
                    return
                await asyncio.sleep(0.02)
            self._act_seq = None
        while time.monotonic() < deadline:
            if self.pending_dialog:
                return
            quiet = self._net_inflight == 0 and (time.monotonic() - self._last_net) * 1000 >= quiet_ms
            if quiet:
                states = []
                for _, fr in self.frames():
                    try:
                        states.append(await fr.evaluate("() => document.readyState"))
                    except PlaywrightError:
                        states.append("loading")
                if all(s == "complete" for s in states):
                    return
            await asyncio.sleep(0.05)

    async def screenshot(self, path: str | None = None, *, mask: list[str] | None = None) -> bytes:
        """PNG of the viewport. `mask` lists sensitivity kinds to black out before capture."""
        if self.pending_dialog:
            raise DialogPending("cannot capture while a native dialog is open")
        frames = [f for _, f in self.frames()]
        if mask:
            for fr in frames:
                await self._eval(fr, "k => window.__us.mask(true, k)", mask)
        try:
            return await self.page.screenshot(path=path, type="png")
        finally:
            if mask:
                for fr in frames:
                    await self._eval(fr, "() => window.__us.mask(false)")
