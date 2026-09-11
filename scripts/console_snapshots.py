"""Capture screenshots of the operator console during a real supervised replay (for the README).

Runs the supervisor-override scenario with the simulated operator (slowed down), and
photographs the console while the session is paused and while the human holds control.
Needs the Keystone mock running. Writes docs/img/console-*.png.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

from understudy.hitl.runtime import operator_console
from understudy.replay.engine import ReplayOptions
from understudy.wiring import load_env, run_replay

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "img"


class Quiet:
    def route(self, request, session):
        pass


async def photographer(center, done: asyncio.Event) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    taken: set[str] = set()
    async with async_playwright() as pw, httpx.AsyncClient(base_url=center.console_base,
                                                            headers={"x-operator-token": center.token}) as http:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1400, "height": 820})
        while not done.is_set() and len(taken) < 2:
            await asyncio.sleep(0.3)
            sessions = (await http.get("/api/sessions")).json()
            if not sessions:
                continue
            s = sessions[0]
            key = "paused" if s["holder"] == "paused" and s["request"] and s["request"]["kind"] == "human_required" else (
                "human" if s["holder"] == "human" else None)
            if key and key not in taken:
                await page.goto(f"{center.console_base}/sessions/{s['run_id']}?token={center.token}")
                await asyncio.sleep(1.6)  # let the live view refresh
                await page.screenshot(path=str(OUT / f"console-{key}.png"))
                taken.add(key)
        await browser.close()


async def main() -> None:
    load_env()
    os.environ.setdefault("UNDERSTUDY_EVIDENCE_DIR", str(ROOT / "evidence" / "scratch"))
    script = ROOT / "scripts" / "slow_supervisor.yaml"
    script.write_text((ROOT / "examples/operators/supervisor_override.yaml").read_text()
                      .replace("think_s: 1.5", "think_s: 4").replace("think_s: 1.0", "think_s: 2"))
    try:
        async with operator_console(Quiet(), port=8799, operator_script=script) as center:
            done = asyncio.Event()
            shots = asyncio.create_task(photographer(center, done))
            res = await run_replay("keystone.member.open_share_account", "lakeshore",
                                   {"member_id": "104410", "product": "Money Market Share", "nickname": "Rainy day fund",
                                    "opening_deposit": "12000", "fund_from": "00"},
                                   control=center, options=ReplayOptions(supervised=True), label="console-snapshots")
            done.set()
            await shots
            print(res.status.value, [p.name for p in OUT.glob("console-*.png")])
    finally:
        script.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(main())
