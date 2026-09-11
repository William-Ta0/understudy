"""Agent-facing capability catalog: saved capabilities as tools an AI agent can discover and call.

The capability's contract maps directly onto a tool definition: inputs become the JSON
Schema of the arguments, and outputs and business outcomes are spelled out in the
description, so the calling agent knows what it gets back and which "no" answers to
expect. Invocation is a deterministic replay; no model is involved on this path.
"""

from __future__ import annotations

from typing import Any

from .registry import CapabilityStore
from .schema import Capability, Lifecycle, ParamSpec, ValueType

_JSON_TYPE = {
    ValueType.string: {"type": "string"},
    ValueType.integer: {"type": "integer"},
    ValueType.decimal: {"type": "string", "pattern": r"^-?\d+(\.\d+)?$"},
    ValueType.money: {"type": "string", "pattern": r"^-?\d+(\.\d{1,2})?$", "description": "decimal amount, e.g. 1500.00"},
    ValueType.date: {"type": "string", "format": "date"},
    ValueType.boolean: {"type": "boolean"},
    ValueType.enum: {"type": "string"},
}


def tool_name(cap_id: str) -> str:
    return cap_id.replace(".", "__")


def _param_schema(p: ParamSpec) -> dict[str, Any]:
    s = dict(_JSON_TYPE[p.type])
    s["description"] = (s.get("description", "") + " " + p.description).strip()
    if p.enum:
        s["enum"] = p.enum
    if p.pattern:
        s["pattern"] = p.pattern
    return s


def _output_schema(cap: Capability) -> dict[str, Any]:
    return {"type": "object", "properties": {k: {**_JSON_TYPE[o.type], "description": o.description} for k, o in cap.outputs.items()}}


def describe(cap: Capability) -> str:
    outs = "; ".join(f"{k} ({o.type.value}): {o.description}" for k, o in cap.outputs.items())
    outcomes = "; ".join(f"{o.code}: {o.description}" for o in cap.outcomes) or "none declared"
    gate = " Includes an irreversible step that pauses for a human approval." if cap.risk.value == "irreversible" else ""
    return (f"{cap.title}. {cap.description} Runs a reviewed, deterministic automation of {cap.app.product} "
            f"(no model in the loop). Returns status succeeded with outputs [{outs}], or business_outcome with a code "
            f"[{outcomes}], or failed with a debuggable reason.{gate}")


def tool_definitions(fmt: str = "anthropic", *, include_unapproved: bool = True) -> list[dict[str, Any]]:
    store = CapabilityStore()
    tools = []
    for cid in store.ids():
        cap = store.load(cid)
        ok = {Lifecycle.approved, Lifecycle.verified} if include_unapproved else {Lifecycle.approved}
        if cap.status not in ok:
            continue
        schema = {
            "type": "object",
            "properties": {"tenant": {"type": "string", "description": "Institution id, e.g. lakeshore"},
                           **{k: _param_schema(p) for k, p in cap.inputs.items()}},
            "required": ["tenant", *[k for k, p in cap.inputs.items() if p.required]],
        }
        if fmt == "openai":
            tools.append({"type": "function", "function": {"name": tool_name(cid), "description": describe(cap), "parameters": schema}})
        elif fmt == "json":
            tools.append({"name": tool_name(cid), "capability": f"{cid}@{cap.version}", "status": cap.status.value,
                          "description": describe(cap), "input_schema": schema, "output_schema": _output_schema(cap),
                          "outcomes": [o.code for o in cap.outcomes]})
        else:
            tools.append({"name": tool_name(cid), "description": describe(cap), "input_schema": schema})
    return tools


def capability_for_tool(name: str) -> str:
    return name.replace("__", ".")
