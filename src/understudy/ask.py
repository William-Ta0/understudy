"""The calling side: an AI agent that answers a question by invoking a capability as a tool.

This is the production path the brief describes. The agent sees the capability catalog
(tool definitions generated from each artifact's contract), picks one, and supplies typed
arguments. The capability runs as a deterministic replay (no model in the loop), and the
agent gets back the structured result: outputs, a business outcome, or a failure.
"""

from __future__ import annotations

import json
from typing import Any

from .agent.llm import LLM
from .catalog import capability_for_tool, tool_definitions
from .evidence import Evidence
from .replay.engine import ReplayOptions
from .safety.redact import Redactor
from .schema import RunResult
from .wiring import evidence_root, run_replay

SYSTEM = """You are a member-service assistant for credit unions. You cannot see any banking system yourself.
You act only through the tools you are given: each one is a reviewed automation of a back-office screen.
Call a tool when it answers the user's question, with arguments exactly as its schema describes.
When a tool returns a business outcome (for example MEMBER_NOT_FOUND), explain it plainly; it is an answer, not an error.
When you have the tool result, reply to the user in one or two sentences without calling more tools."""


def _caller_view(res: RunResult) -> dict[str, Any]:
    """What the calling agent receives: the contract's result, without engine internals."""
    view: dict[str, Any] = {"status": res.status.value}
    if res.outputs is not None:
        view["outputs"] = res.outputs
    if res.outcome:
        view["outcome"] = {"code": res.outcome.code, "description": res.outcome.description, "message": res.outcome.message}
    if res.failure:
        view["failure"] = {"code": res.failure.code.value, "message": res.failure.message, "retryable": res.failure.retryable}
    return view


async def ask(question: str, llm: LLM) -> dict[str, Any]:
    tools = tool_definitions("anthropic")
    redactor = Redactor()
    ev = Evidence(evidence_root(), "agent", "ask", redactor)
    ev.event("question", actor="user", text=question, tools=[t["name"] for t in tools])
    first = await llm.decide(SYSTEM, f"User: {question}", None, tools)
    ev.event("llm_decision", actor="agent", said=first.text[:400], tool=first.calls[0].name if first.calls else None,
             args=first.calls[0].args if first.calls else None)
    if not first.calls:
        ev.event("answer", actor="agent", text=first.text)
        ev.close()
        return {"answer": first.text, "tool": None, "evidence": str(ev.dir)}
    call = first.calls[0]
    args = dict(call.args)
    tenant = str(args.pop("tenant", "lakeshore"))
    cap_id = capability_for_tool(call.name)
    res = await run_replay(cap_id, tenant, args, options=ReplayOptions(), label="via-agent")
    view = _caller_view(res)
    for k, v in (res.outputs or {}).items():  # the agent may see the values; the evidence may not
        from .registry import CapabilityStore

        redactor.register(str(v), CapabilityStore().load(cap_id).outputs[k].sensitivity, k)
    ev.event("tool_result", actor="system", capability=cap_id, tenant=tenant, replay_run=res.run_id,
             replay_evidence=res.evidence_dir, result=view)
    followup = (f"User: {question}\n\nYou called {call.name} with {json.dumps(call.args)}.\n"
                f"It returned: {json.dumps(view)}\n\nNow answer the user.")
    second = await llm.decide(SYSTEM, followup, None, tools)
    ev.event("answer", actor="agent", text=second.text)
    ev.close()
    return {"answer": second.text, "tool": call.name, "args": call.args, "result": view, "evidence": str(ev.dir),
            "replay_evidence": res.evidence_dir}
