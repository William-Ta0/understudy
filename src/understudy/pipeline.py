"""The discovery pipeline: discover -> compile -> verify (no model) -> save as a draft/verified capability."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .agent.discover import DiscoveryAgent
from .agent.llm import LLM
from .compile.compiler import CompileError, Compiler
from .hitl.control import ControlCenter
from .registry import CapabilityStore, load_goal, to_yaml
from .replay.engine import ReplayOptions
from .report import write_run_report
from .schema import Capability, Lifecycle, RunResult, RunStatus, Trace, VerificationRecord
from .wiring import open_env, run_replay


@dataclass
class DiscoveryOutcome:
    trace: Trace
    evidence_dir: str
    capability: Capability | None = None
    saved_to: str | None = None
    verification: RunResult | None = None
    compile_error: str | None = None


async def discover(goal_ref: str, tenant_id: str, inputs: dict[str, Any], llm: LLM, *, control: ControlCenter | None = None,
                   headless: bool = True, verify: bool = True, save: bool = True) -> DiscoveryOutcome:
    goal = load_goal(goal_ref)
    env = await open_env(tenant_id, kind="discovery", label=goal.capability.split(".")[-1], control=control, headless=headless)
    agent = DiscoveryAgent(goal, inputs, env, llm)
    try:
        trace = await agent.run()
    finally:
        if control:
            control.close(env.evidence.run_id)
        await env.close()
    out = DiscoveryOutcome(trace=trace, evidence_dir=str(env.evidence.dir))
    if not trace.finish or trace.finish.status != "success":
        write_run_report(env.evidence.dir, f"Discovery: {goal.title} (did not succeed)")
        return out

    store = CapabilityStore()
    try:
        cap = Compiler(env.profile, env.tenant, env.redactor).compile(trace, agent.inputs, store)
    except CompileError as e:
        out.compile_error = str(e)
        (env.evidence.dir / "compile-error.txt").write_text(str(e) + "\n" + "\n".join(f"[{n.level}] {n.message}" for n in e.notes))
        write_run_report(env.evidence.dir, f"Discovery: {goal.title} (compile failed)")
        return out

    if verify:
        # Prove the artifact replays without the model. Never commits: stops before any irreversible step.
        res = await run_replay(cap, tenant_id, inputs, options=ReplayOptions(stop_before_irreversible=True), label="verify",
                               headless=headless)
        out.verification = res
        rec = VerificationRecord(run_id=res.run_id, at=datetime.now(timezone.utc), tenant=tenant_id, status=res.status.value,
                                 duration_ms=res.duration_ms)
        prov = cap.provenance.model_copy(update={"verifications": [*cap.provenance.verifications, rec]})
        update: dict[str, Any] = {"provenance": prov}
        if res.status == RunStatus.succeeded:
            update["status"] = Lifecycle.verified
            mism = [k for k, fp in trace.extracted.items()
                    if res.outputs and k in res.outputs and env.redactor.fingerprint(str(res.outputs[k])) != fp["fingerprint"]]
            if mism:
                from .schema import ReviewNote

                notes = [*cap.review.notes, ReviewNote(level="warning", message=f"verification outputs differ from discovery: {mism}")]
                update["review"] = cap.review.model_copy(update={"notes": notes})
        cap = cap.model_copy(update=update)
        write_run_report(__import__("pathlib").Path(res.evidence_dir or ""), f"Verification replay of {cap.id}@{cap.version}")
    out.capability = cap
    (env.evidence.dir / "capability.yaml").write_text(to_yaml(cap, f"# compiled from discovery run {trace.run_id}"))
    if save:
        out.saved_to = str(store.save(cap))
    write_run_report(env.evidence.dir, f"Discovery: {goal.title}")
    return out
