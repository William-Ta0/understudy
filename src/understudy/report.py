"""Human-readable renderings: a run's timeline (report.md) and a capability card."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .schema import Capability, describe_locator, summarize

ICON = {
    "step_started": "▶", "step_completed": "✓", "action_performed": "·", "condition_detected": "⚑", "recovery": "↻",
    "business_outcome": "◆", "failure": "✗", "locator_drift": "≈", "output_extracted": "⇥", "checkpoint_passed": "✓",
    "intervention_requested": "✋", "control_transferred": "⇄", "human_action": "👤", "policy_blocked_action": "⛔",
    "policy_blocked_request": "⛔", "llm_decision": "🧠", "trace_step": "·", "run_finished": "■", "agent_finished": "■",
    "sign_on_completed": "🔑", "flow_restarted": "↺", "approval_granted": "✔", "resynced": "⇄", "stopped_before_irreversible": "⏸",
}

SKIP = {"sign_on_step", "policy_decision", "step_completed", "trace_step", "automation_parked"}


def _line(e: dict[str, Any]) -> str | None:
    t = e["type"]
    if t in SKIP:
        return None
    icon = ICON.get(t, "·")
    d = {k: v for k, v in e.items() if k not in ("seq", "ts", "t", "run_id", "actor", "type")}
    if t == "llm_decision":
        args = d.get("args") or {}
        brief = ", ".join(f"{k}={v}" for k, v in args.items() if k in ("ref", "value", "option", "output", "text", "kind", "status"))
        said = f' - "{args.get("intent") or d.get("said", "")}"' if (args.get("intent") or d.get("said")) else ""
        shot = f" ([screen]({d['screenshot']}))" if d.get("screenshot") else ""
        return f"{icon} turn {d.get('turn')} on `{d.get('screen')}`: **{d.get('tool')}**({brief}){said}{shot}"
    if t == "step_started":
        return f"{icon} **{d.get('step')}** ({d.get('action')}): {d.get('intent')}"
    if t == "action_performed":
        extra = d.get("value") or d.get("option") or d.get("key") or ""
        return f"  {icon} {d.get('action')} {extra}".rstrip()
    if t == "condition_detected":
        return f"{icon} runtime condition `{d.get('id')}` ({d.get('kind')}): {d.get('message') or ''}"
    if t == "recovery":
        return f"{icon} recovery for `{d.get('condition')}`: {d.get('action')} (attempt {d.get('attempt')})"
    if t == "business_outcome":
        return f"{icon} business outcome **{d.get('code')}**: {d.get('message') or ''}"
    if t == "failure":
        ev = d.get("evidence") or {}
        links = " ".join(f"[{k}]({v})" for k, v in ev.items())
        return f"{icon} failure **{d.get('code')}** at `{d.get('step')}`: {d.get('message')} - expected: {d.get('expected')}; observed: {d.get('observed')} {links}"
    if t == "output_extracted":
        return f"{icon} output `{d.get('output')}` via {d.get('locator')}: {json.dumps(d.get('value'))}"
    if t == "locator_drift":
        return f"{icon} locator drift at `{d.get('step')}`: primary {d.get('primary')} missed, used {d.get('used')}"
    if t == "intervention_requested":
        shot = f" ([screen]({d['screenshot']}))" if d.get("screenshot") else ""
        return f"{icon} intervention **{d.get('kind')}**: {d.get('reason')}{shot}"
    if t == "control_transferred":
        who = f" by {d.get('operator')}" if d.get("operator") else ""
        return f"{icon} control {d.get('from')} → **{d.get('to')}**{who} (epoch {d.get('epoch')}) {d.get('resolution') or ''}".rstrip()
    if t == "human_action":
        a = d.get("action") or {}
        tg = a.get("target") or {}
        return f"{icon} human {a.get('kind')} {tg.get('role', '')} \"{tg.get('label') or tg.get('name') or tg.get('text', '')}\" {a.get('value') or ''}".rstrip()
    if t in ("policy_blocked_action", "policy_blocked_request"):
        return f"{icon} policy blocked {d.get('action') or d.get('url')}: {d.get('reason')}"
    if t == "checkpoint_passed":
        return f"{icon} success checkpoint: {d.get('condition')}"
    if t in ("run_finished", "agent_finished", "discovery_finished"):
        return f"{icon} **{t.replace('_', ' ')}**: " + ", ".join(f"{k}={v}" for k, v in d.items() if v is not None and k != "llm")
    return f"{icon} {t}: " + ", ".join(f"{k}={v}" for k, v in d.items() if v not in (None, "", [], {}))[:300]


def write_run_report(run_dir: Path, title: str) -> Path:
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines() if line.strip()]
    lines = [f"# {title}", "", f"Run `{events[0]['run_id'] if events else '?'}`. Every line below comes from `events.jsonl`; "
             "screenshots are masked before capture.", "", "| t (s) | event |", "|---:|---|"]
    for e in events:
        ln = _line(e)
        if ln:
            lines.append(f"| {e['t']:.2f} | {ln.replace('|', '/')} |")
    result = run_dir / "result.json"
    if result.exists():
        lines += ["", "## Result (as persisted: masked outputs are placeholders + fingerprints)", "", "```json",
                  result.read_text()[:6000], "```"]
    p = run_dir / "report.md"
    p.write_text("\n".join(lines) + "\n")
    return p


def capability_card(cap: Capability) -> str:
    """The reviewer's one-screen view of a capability."""
    out = [f"{cap.title}  [{cap.id}@{cap.version}, {cap.status.value}, risk={cap.risk.value}]", f"  {cap.description}", ""]
    out.append("  inputs:")
    for k, p in cap.inputs.items():
        out.append(f"    {k}: {p.type.value}{' (optional)' if not p.required else ''}  [{p.sensitivity.value}]  {p.description}")
    out.append("  outputs:")
    for k, o in cap.outputs.items():
        out.append(f"    {k}: {o.type.value}  [{o.sensitivity.value}]  {o.description}  <- {describe_locator(o.source.primary)}")
    out.append("  business outcomes:")
    for o in cap.outcomes:
        out.append(f"    {o.code}: {o.description}  (condition {o.condition})")
    out.append(f"  entry: {cap.entry.screen}")
    out.append("  steps:")
    for i, s in enumerate(cap.steps, 1):
        tgt = getattr(s, "target", None)
        loc = f"  <- {describe_locator(tgt.primary)} (+{len(tgt.locators) - 1} fallback)" if tgt else ""
        gate = "  [APPROVAL]" if s.approval == "required" else ""
        who = "  [human at discovery]" if s.origin == "human" else ""
        out.append(f"    {i}. {s.id} ({s.action}, {s.risk.value}){gate}{who}: {s.intent}{loc}")
        if s.expect is not None:
            out.append(f"         checkpoint: {summarize(s.expect)}")
    out.append(f"  success: {summarize(cap.success)}")
    if cap.review.notes:
        out.append("  review notes:")
        for n in cap.review.notes:
            out.append(f"    [{n.level}] {n.step + ': ' if n.step else ''}{n.message}")
    out.append(f"  content hash: {cap.content_hash()}  approved: {cap.is_approved()}")
    return "\n".join(out)
