"""understudy command line.

    understudy mock                                  run the Keystone Core mock (the target app)
    understudy discover GOAL -t TENANT -i k=v        LLM discovery -> compile -> verify -> save
    understudy replay CAP -t TENANT -i k=v           deterministic replay (no model)
    understudy show CAP / list / approve CAP         review and lifecycle
    understudy catalog                               capabilities as agent tool definitions
    understudy fault KIND ...                        inject a runtime fault into the mock (demos)
    understudy schema                                export JSON Schemas for every document type
"""

from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel

from .schema import Approval, Capability, InterventionRequest, Lifecycle, RunResult, RunStatus

app = typer.Typer(help="understudy: learn a back-office UI flow once with an LLM, replay it deterministically.",
                  no_args_is_help=True, add_completion=False, pretty_exceptions_show_locals=False)
out = Console()

KV = typer.Option([], "--input", "-i", help="Input as name=value. Repeatable.")


def _kv(pairs: list[str]) -> dict[str, str]:
    d = {}
    for p in pairs:
        if "=" not in p:
            raise typer.BadParameter(f"expected name=value, got {p!r}")
        k, v = p.split("=", 1)
        d[k.strip()] = v
    return d


# --------------------------------------------------------------------------- live terminal output


def _printer(verbose: bool):
    def show(e: dict[str, Any]) -> None:
        t, d = e["type"], e
        ts = f"[dim]{e['t']:6.2f}s[/]"
        if t == "step_started":
            out.print(f"{ts} [bold]▶ {d['step']}[/] [dim]{d.get('intent', '')}[/]")
        elif t == "llm_decision":
            a = d.get("args") or {}
            brief = " ".join(f"{k}={v}" for k, v in a.items() if k in ("ref", "value", "option", "output", "text", "status", "kind"))
            out.print(f"{ts} [magenta]🧠 turn {d['turn']}[/] on [cyan]{d.get('screen')}[/]: [bold]{d.get('tool')}[/] {brief} "
                      f"[dim]{a.get('intent') or a.get('reason') or a.get('summary') or ''}[/]")
        elif t == "trace_step" and not d.get("ok", True):
            out.print(f"{ts}   [red]⛔ {d.get('error')}[/]")
        elif t == "condition_detected":
            out.print(f"{ts} [yellow]⚑ {d['id']}[/] ({d['kind']}) [dim]{d.get('message') or ''}[/]")
        elif t == "recovery":
            out.print(f"{ts} [yellow]↻ recovered {d['condition']}[/] via {d['action']} (attempt {d['attempt']})")
        elif t == "locator_drift":
            out.print(f"{ts} [yellow]≈ drift at {d['step']}[/]: {d['primary']} missed; used {d['used']}")
        elif t == "output_extracted":
            out.print(f"{ts} [green]⇥ {d['output']}[/] = {json.dumps(d['value'])}")
        elif t == "business_outcome":
            out.print(f"{ts} [blue]◆ business outcome {d['code']}[/]: {d.get('message') or ''}")
        elif t == "failure":
            out.print(f"{ts} [red]✗ {d['code']}[/] at {d.get('step')}: {d['message']}")
        elif t == "control_transferred":
            out.print(f"{ts} [bold cyan]⇄ control {d['from']} → {d['to']}[/] (epoch {d['epoch']}) {d.get('resolution') or ''}")
        elif t == "human_action":
            a = d.get("action") or {}
            tg = a.get("target") or {}
            out.print(f"{ts} [cyan]👤 {a.get('kind')}[/] {tg.get('role', '')} \"{tg.get('label') or tg.get('name') or tg.get('text', '')}\" {a.get('value') or ''}")
        elif t in ("policy_blocked_action", "policy_blocked_request"):
            out.print(f"{ts} [red]⛔ policy[/]: {d.get('reason')}")
        elif t == "sign_on_completed":
            out.print(f"{ts} [dim]🔑 signed on[/]")
        elif t == "flow_restarted":
            out.print(f"{ts} [yellow]↺ flow restarted[/] after re-establishing the session")
        elif t == "stopped_before_irreversible":
            out.print(f"{ts} [dim]⏸ verification stops before irreversible step {d['step']}[/]")
        elif verbose and t not in ("policy_decision", "sign_on_step"):
            out.print(f"{ts} [dim]{t}[/]")
    return show


class TerminalRouter:
    """Routes intervention requests to the terminal. Production would page an operator queue."""

    def route(self, request: InterventionRequest, session: Any) -> None:
        body = f"[bold]{request.kind}[/]: {request.reason}\n"
        if request.context.get("step"):
            body += f"step: {request.context['step']}\n"
        body += f"screen: {request.context.get('screen')}\n"
        if request.console_url:
            body += f"\nOpen the operator console to take over this live session:\n[link]{request.console_url}[/link]"
        out.print(Panel(body, title="✋ intervention requested", border_style="yellow"))


@asynccontextmanager
async def _control(enabled: bool, port: int, operator_script: Path | None):
    if not enabled:
        yield None
        return
    from .hitl.runtime import operator_console

    async with operator_console(TerminalRouter(), port=port, operator_script=operator_script) as center:
        out.print(f"[dim]operator console: {center.console_base}/?token={center.token}[/]")
        yield center
        sim = getattr(center, "operator_task", None)
        if sim is not None and sim.done() and sim.exception() is not None:
            out.print(f"[red]operator script failed: {sim.exception()}[/]")


def _listen(verbose: bool) -> None:
    from .evidence import GLOBAL_LISTENERS

    GLOBAL_LISTENERS.append(_printer(verbose))


def _print_result(res: RunResult, *, reveal: bool) -> None:
    color = {"succeeded": "green", "business_outcome": "blue", "failed": "red"}[res.status.value]
    lines = [f"[bold {color}]{res.status.value}[/]  {res.capability['id']}@{res.capability['version']} on {res.tenant}  "
             f"({res.duration_ms} ms)"]
    if res.outputs is not None:
        shown = res.outputs if reveal else {k: "<returned to caller; pass --reveal to print>" for k in res.outputs}
        lines.append("outputs: " + json.dumps(shown, indent=2))
    if res.outcome:
        lines.append(f"outcome: [bold]{res.outcome.code}[/] - {res.outcome.description}\napp said: {res.outcome.message}")
    if res.failure:
        f = res.failure
        lines.append(f"failure: [bold]{f.code.value}[/] at step {f.step_id}: {f.message}\nexpected: {f.expected}\nobserved: {f.observed}"
                     f"\nretryable: {f.retryable}\nevidence: {f.evidence}")
    if res.recoveries:
        lines.append("recovered: " + ", ".join(f"{r.condition}→{r.action}" for r in res.recoveries))
    if res.warnings:
        lines.append("warnings:\n" + "\n".join(f"  - {w.kind}: {w.message}" for w in res.warnings))
    if res.interventions:
        lines.append("interventions: " + ", ".join(f"{i.kind}→{i.resolution} by {i.operator} ({i.human_actions} actions)" for i in res.interventions))
    lines.append(f"evidence: {res.evidence_dir}")
    out.print(Panel("\n".join(lines), title="replay result", border_style=color))


# --------------------------------------------------------------------------- commands


@app.command()
def mock(port: int = typer.Option(8765), idle_timeout: float = typer.Option(900, help="Session idle timeout (s).")):
    """Run the Keystone Core mock: the legacy teller workstation understudy is demonstrated against."""
    import uvicorn

    from keystone_mock import create_app

    out.print(f"Keystone Core mock on http://127.0.0.1:{port}/t/lakeshore/signon.asp (and /t/pinecrest/)")
    uvicorn.run(create_app(idle_timeout_s=idle_timeout), host="127.0.0.1", port=port, log_level="warning")


@app.command()
def discover(
    goal: str = typer.Argument(..., help="Goal file or name under goals/."),
    tenant: str = typer.Option("lakeshore", "--tenant", "-t"),
    inputs: list[str] = KV,
    llm: str = typer.Option(None, help="anthropic | openai | scripted:<path>. Default: $UNDERSTUDY_LLM or anthropic."),
    console: bool = typer.Option(True, help="Serve the operator console so a human can take over."),
    console_port: int = typer.Option(8766),
    operator_script: Path = typer.Option(None, help="Simulated operator script (tests/demos)."),
    headed: bool = typer.Option(False, help="Show the browser window."),
    verify: bool = typer.Option(True, help="Replay the compiled capability once without the model."),
    save: bool = typer.Option(True, help="Save the capability to capabilities/."),
    verbose: bool = typer.Option(False, "-v"),
):
    """Run the LLM agent on a goal, compile the run into a capability, and verify it replays without the model."""
    from .agent.llm import make_llm
    from .pipeline import discover as run
    from .report import capability_card
    from .wiring import load_env

    load_env()
    _listen(verbose)

    async def main():
        async with _control(console or operator_script is not None, console_port, operator_script) as center:
            return await run(goal, tenant, _kv(inputs), make_llm(llm), control=center, headless=not headed, verify=verify, save=save)

    res = asyncio.run(main())
    t = res.trace
    from rich.markup import escape

    out.print(Panel(f"status: [bold]{t.finish.status if t.finish else '?'}[/] - {escape(t.finish.summary) if t.finish else ''}\n"
                    f"agent steps: {sum(1 for s in t.steps if s.actor == 'agent')}, human steps: "
                    f"{sum(1 for s in t.steps if s.actor == 'human')}, model: {t.llm.model if t.llm else '?'} "
                    f"({t.llm.calls if t.llm else 0} calls, {t.llm.input_tokens if t.llm else 0} in / {t.llm.output_tokens if t.llm else 0} out tokens)\n"
                    f"evidence: {res.evidence_dir}", title="discovery", border_style="magenta"))
    if res.compile_error:
        out.print(f"[red]compile failed:[/] {res.compile_error}")
        raise typer.Exit(2)
    if res.capability:
        out.print(capability_card(res.capability), markup=False, highlight=False)
        if res.verification:
            out.print(f"verification replay: [bold]{res.verification.status.value}[/] ({res.verification.evidence_dir})")
        if res.saved_to:
            out.print(f"saved: [bold]{res.saved_to}[/]")
    if not res.capability:
        raise typer.Exit(1)


@app.command()
def replay(
    capability: str = typer.Argument(..., help="Capability id[@version] or a YAML path."),
    tenant: str = typer.Option("lakeshore", "--tenant", "-t"),
    inputs: list[str] = KV,
    supervised: bool = typer.Option(False, help="Escalate to a human instead of failing when stuck; allows approvals."),
    console_port: int = typer.Option(8766),
    operator_script: Path = typer.Option(None, help="Simulated operator script (tests/demos)."),
    require_approved: bool = typer.Option(False, help="Refuse capabilities that are not approved (production mode)."),
    headed: bool = typer.Option(False),
    label: str = typer.Option(None, help="Evidence folder label."),
    no_overrides: bool = typer.Option(False, help="Ignore the tenant's vocabulary/overrides (shows raw drift on a variant)."),
    json_out: bool = typer.Option(False, "--json", help="Print the caller-facing result as JSON."),
    reveal: bool = typer.Option(False, help="Print output values (they are never written to disk)."),
    verbose: bool = typer.Option(False, "-v"),
):
    """Replay a capability deterministically with typed inputs. No model is called."""
    from .replay.engine import ReplayOptions
    from .report import write_run_report
    from .wiring import load_env, run_replay

    load_env()
    if not json_out:
        _listen(verbose)

    async def main():
        hitl = supervised or operator_script is not None
        async with _control(hitl, console_port, operator_script) as center:
            opts = ReplayOptions(supervised=supervised, require_approved=require_approved)
            return await run_replay(capability, tenant, _kv(inputs), options=opts, control=center, headless=not headed, label=label,
                                    tenant_overrides=not no_overrides)

    res = asyncio.run(main())
    if res.evidence_dir:
        write_run_report(Path(res.evidence_dir), f"Replay of {res.capability['id']}@{res.capability['version']} on {res.tenant}")
    if json_out:
        print(res.model_dump_json(indent=2))
    else:
        _print_result(res, reveal=reveal)
    raise typer.Exit(0 if res.status != RunStatus.failed else 1)


@app.command()
def show(capability: str):
    """Print a capability's reviewer card: contract, steps, locators, checkpoints, review notes."""
    from .registry import CapabilityStore
    from .report import capability_card

    out.print(capability_card(CapabilityStore().load(capability)), markup=False, highlight=False)


@app.command("list")
def list_():
    """List capabilities in the store."""
    from .registry import CapabilityStore

    store = CapabilityStore()
    for cid in store.ids():
        cap = store.load(cid)
        out.print(f"{cid}  versions={store.versions(cid)}  latest={cap.status.value}  approved={cap.is_approved()}  risk={cap.risk.value}")


@app.command()
def approve(capability: str, by: str = typer.Option(..., "--by"), note: str = typer.Option(None)):
    """Approve a verified capability for unattended use. The approval binds to its content hash."""
    from .registry import CapabilityStore

    store = CapabilityStore()
    cap = store.load(capability)
    if cap.status not in (Lifecycle.verified, Lifecycle.approved):
        out.print(f"[red]{cap.id}@{cap.version} is {cap.status.value}; only verified capabilities can be approved[/]")
        raise typer.Exit(1)
    blockers = [n for n in cap.review.notes if n.level == "blocker"]
    if blockers:
        out.print(f"[red]{len(blockers)} blocker note(s) must be resolved first[/]")
        raise typer.Exit(1)
    appr = Approval(by=by, at=datetime.now(timezone.utc), content_hash=cap.content_hash(), note=note)
    cap = cap.model_copy(update={"status": Lifecycle.approved, "review": cap.review.model_copy(update={"approvals": [*cap.review.approvals, appr]})})
    path = store.save(cap)
    out.print(f"approved {cap.id}@{cap.version} ({appr.content_hash}) -> {path}")


@app.command()
def catalog(fmt: str = typer.Option("anthropic", "--format", help="anthropic | openai | json")):
    """Print approved/verified capabilities as tool definitions an agent can call by name."""
    from .catalog import tool_definitions

    print(json.dumps(tool_definitions(fmt), indent=2))


@app.command()
def ask(question: str = typer.Argument(..., help="A question a member-service agent would answer with a capability."),
        llm: str = typer.Option(None, help="anthropic | openai. Default: $UNDERSTUDY_LLM.")):
    """Let an AI agent answer a question by calling a saved capability as a tool (replay runs without the model)."""
    from .agent.llm import make_llm
    from .ask import ask as run
    from .wiring import load_env

    load_env()
    res = asyncio.run(run(question, make_llm(llm)))
    out.print(Panel(f"tool: {res.get('tool')} {json.dumps(res.get('args') or {})}\n"
                    f"result status: {(res.get('result') or {}).get('status')}\n\n[bold]{res['answer']}[/]\n\n"
                    f"evidence: {res['evidence']}", title="agent", border_style="cyan"))


@app.command()
def fault(kind: str = typer.Argument(..., help="session_expired | notice | host_error | slow | server_error | deny | reset"),
          tenant: str = typer.Option(None, "--tenant", "-t"), page: str = typer.Option(None), method: str = typer.Option(None),
          count: int = typer.Option(1), delay_ms: int = typer.Option(0)):
    """Arm a runtime fault in the Keystone mock (it fires on the next matching request)."""
    import httpx

    base = os.environ.get("KEYSTONE_BASE_URL", "http://127.0.0.1:8765")
    if kind == "reset":
        httpx.post(f"{base}/__control/reset").raise_for_status()
        out.print("mock reset")
        return
    body = {k: v for k, v in dict(kind=kind, tenant=tenant, page=page, method=method, count=count, delay_ms=delay_ms).items() if v is not None}
    r = httpx.post(f"{base}/__control/faults", json=body)
    r.raise_for_status()
    out.print(r.json())


@app.command()
def schema(out_dir: Path = typer.Option(Path("docs/schema"), "--out")):
    """Export JSON Schemas for capability, app profile, tenant, policy, goal, and run result."""
    from .schema import AppProfile, GoalSpec, Policy, TenantBinding

    out_dir.mkdir(parents=True, exist_ok=True)
    for name, m in {"capability": Capability, "app-profile": AppProfile, "tenant": TenantBinding, "policy": Policy,
                    "goal": GoalSpec, "run-result": RunResult}.items():
        (out_dir / f"{name}.schema.json").write_text(json.dumps(m.model_json_schema(by_alias=True), indent=2))
    out.print(f"wrote JSON Schemas to {out_dir}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
