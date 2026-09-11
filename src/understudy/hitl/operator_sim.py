"""A scripted stand-in for a human operator, for tests and unattended demos.

It uses the operator console's HTTP API exactly as the browser console does: waits for an
intervention, claims the session, aims clicks at elements it finds in the live UI by what
they say, types, and releases with a resolution. Secrets it types come from the
environment, never from the script. Everything it does is captured by the same page-level
capture as a real operator's actions.

    operator: sup_kim
    handlers:
      - on: human_required            # intervention kind to wait for
        actions:
          - click: {label: Supervisor ID}
          - type: sup_kim
          - click: {label: Override Code}
          - type_env: KEYSTONE_SUPERVISOR_CODE
          - click: {role: button, name: Submit Override}
        release: {resolution: resume, note: override entered at the workstation}
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import httpx
import yaml


def _norm(s: Any) -> str:
    return " ".join(str(s or "").split()).lower()


def _match(node: dict[str, Any], m: dict[str, Any]) -> bool:
    for k in ("role", "name", "label", "text", "frame"):
        if k in m and _norm(node.get(k)) != _norm(m[k]):
            return False
    return True


async def run_operator(console_base: str, token: str, script_path: str | Path, *, poll_s: float = 0.4,
                       timeout_s: float = 300) -> list[dict[str, Any]]:
    script = yaml.safe_load(Path(script_path).read_text())
    operator = script.get("operator", "operator-sim")
    handlers = list(script.get("handlers", []))
    done: list[dict[str, Any]] = []
    headers = {"x-operator-token": token}
    async with httpx.AsyncClient(base_url=console_base, headers=headers, timeout=30) as http:
        deadline = asyncio.get_running_loop().time() + timeout_s
        while handlers and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(poll_s)
            try:
                sessions = (await http.get("/api/sessions")).json()
            except httpx.HTTPError:
                continue
            pending = next((s for s in sessions if s["request"] and s["holder"] == "paused"), None)
            if not pending:
                continue
            h = handlers[0]
            if h.get("on") and pending["request"]["kind"] != h["on"]:
                continue
            handlers.pop(0)
            rid = pending["run_id"]
            await asyncio.sleep(float(h.get("think_s", 1.0)))  # a human reads the request first
            actions = h.get("actions", [])
            if actions:
                r = await http.post(f"/api/sessions/{rid}/claim", json={"operator": operator})
                r.raise_for_status()
            for act in actions:
                await _do(http, rid, operator, act)
                await asyncio.sleep(float(h.get("pace_s", 0.6)))
            rel = h.get("release", {"resolution": "resume"})
            r = await http.post(f"/api/sessions/{rid}/release", json={"operator": operator, **rel})
            r.raise_for_status()
            done.append({"run_id": rid, "kind": pending["request"]["kind"], "resolution": rel["resolution"]})
    return done


async def _do(http: httpx.AsyncClient, rid: str, operator: str, act: dict[str, Any]) -> None:
    if "click" in act:
        for _ in range(20):
            ui = (await http.get(f"/api/sessions/{rid}/ui")).json()
            node = next((n for n in ui.get("nodes", []) if _match(n, act["click"])), None)
            if node:
                break
            await asyncio.sleep(0.3)
        else:
            raise RuntimeError(f"operator could not find {act['click']}")
        await http.post(f"/api/sessions/{rid}/input", json={"operator": operator, "kind": "click", "x": node["x"], "y": node["y"]})
    elif "type" in act:
        await http.post(f"/api/sessions/{rid}/input", json={"operator": operator, "kind": "type", "text": str(act["type"])})
    elif "type_env" in act:
        value = os.environ.get(act["type_env"])
        if value is None:
            raise RuntimeError(f"operator script needs ${act['type_env']}")
        await http.post(f"/api/sessions/{rid}/input", json={"operator": operator, "kind": "type", "text": value})
    elif "key" in act:
        await http.post(f"/api/sessions/{rid}/input", json={"operator": operator, "kind": "key", "key": str(act["key"])})
    elif "dialog" in act:
        await http.post(f"/api/sessions/{rid}/input", json={"operator": operator, "kind": "dialog", "accept": bool(act["dialog"])})
