"""The discovery agent's instructions and tool surface.

The tools are deliberately few and surface-agnostic: act on an element by ref, read an
element into a declared output, assert a checkpoint, ask a human, finish. Every argument
the model writes (`intent`, `purpose`) exists because the compiler needs it.
"""

from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """\
You are the discovery agent of a system that automates bank back-office applications with no API.
You operate the application's user interface the way a trained operator would. Your run is recorded:
each action you take becomes a step in a reusable, deterministic procedure that will later be replayed
without you, for other inputs and often for other institutions running the same software. So demonstrate
the procedure the way you would for a new colleague: take the direct path, one deliberate action per turn.

Each turn you get the goal, the declared inputs and outputs, what has happened so far, and the current
screen as a screenshot plus a UI map. Every element in the UI map has a ref such as [m12]; the part before
the number identifies the frame. The application is an old frameset UI: a navigation frame on the left,
the working area in the "main" frame. Clickable table cells in menus are shown as "(clickable <td>)".

How to act:
- Call exactly one tool per turn. Target elements by ref from the current UI map only. Use click_at only
  when the element you need has no ref.
- When a value comes from the declared inputs, type the placeholder (for example {{inputs.member_id}}),
  never the literal value; the system substitutes it. Never invent or guess data.
- Give every action a short `intent` (what and why) and a `purpose`:
  flow = a step of the procedure itself; incidental = handling something that may not happen next time
  (an unexpected notice, a retry after a transient error); exploratory = looking around, not part of the
  procedure.
- When you reach a state that proves progress (the right record is open, the review screen is showing),
  record a checkpoint that a machine can verify, such as a heading text.
- Read each declared output with `extract`, pointing at the element that shows the value itself (the table
  cell, not its column header or its label).
- Values shown as [pii] or [secret] are hidden for privacy. You do not need to see them.

Limits you must respect:
- Irreversible actions (confirming, posting, approving, submitting an override) are blocked for you by
  policy. If the goal needs one, stop on the screen right before it and call request_human with
  kind "approval"; a human operator will decide and act in this same session, then hand it back.
- If you are blocked (missing information, credentials or an override code you do not have, access denied,
  an error that repeats), call request_human with a clear reason instead of guessing.
- If the goal cannot be achieved for a legitimate business reason (for example the record does not exist),
  call finish with status "impossible" and say why.
- When every declared output is extracted and the goal's end state is on screen, call finish with status
  "success".
"""

_PURPOSE = {"type": "string", "enum": ["flow", "incidental", "exploratory"],
            "description": "flow: part of the procedure. incidental: situational handling. exploratory: not part of the procedure."}
_INTENT = {"type": "string", "description": "What this action does and why, in a few words."}


def _action(name: str, description: str, props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": {**props, "intent": _INTENT, "purpose": _PURPOSE},
            "required": [*required, "intent", "purpose"],
        },
    }


TOOLS: list[dict[str, Any]] = [
    _action("click", "Click an element (button, link, menu cell, checkbox).",
            {"ref": {"type": "string", "description": "Element ref from the current UI map, e.g. m12."}}, ["ref"]),
    _action("fill", "Replace the content of a text field.",
            {"ref": {"type": "string"},
             "value": {"type": "string", "description": "Text to type. Use {{inputs.<name>}} for declared inputs."}},
            ["ref", "value"]),
    _action("select_option", "Choose an option in a drop-down by its visible label.",
            {"ref": {"type": "string"},
             "option": {"type": "string", "description": "Visible option label, or the option value shown as (=value), or {{inputs.<name>}}."}},
            ["ref", "option"]),
    _action("press_key", "Press a key, optionally with focus on an element.",
            {"key": {"type": "string", "description": "e.g. Enter, Tab, Escape."}, "ref": {"type": "string"}}, ["key"]),
    _action("handle_dialog", "Answer the native dialog (alert/confirm) that is blocking the page.",
            {"accept": {"type": "boolean", "description": "true = OK, false = Cancel."}}, ["accept"]),
    _action("click_at", "Click at page coordinates. Only when the element you need has no ref.",
            {"x": {"type": "number"}, "y": {"type": "number"}}, ["x", "y"]),
    {
        "name": "extract",
        "description": "Read a declared output from the element that displays it.",
        "input_schema": {
            "type": "object",
            "properties": {"output": {"type": "string", "description": "Name of a declared output."},
                           "ref": {"type": "string", "description": "Element showing the value."},
                           "intent": _INTENT},
            "required": ["output", "ref", "intent"],
        },
    },
    {
        "name": "checkpoint",
        "description": "Assert a verifiable fact about the current screen. It is checked immediately and recorded.",
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "What this proves, e.g. 'member detail for the member is open'."},
                "text": {"type": "string", "description": "Text that must be visible (may use {{inputs.<name>}})."},
                "frame": {"type": "string", "description": "Frame the text must be in, e.g. main."},
            },
            "required": ["description", "text"],
        },
    },
    {
        "name": "wait",
        "description": "Wait for the application (at most 5 seconds).",
        "input_schema": {"type": "object", "properties": {"seconds": {"type": "number"}, "reason": {"type": "string"}},
                         "required": ["seconds", "reason"]},
    },
    {
        "name": "request_human",
        "description": "Pause and hand the live session to a human operator. They act in this same session and hand it back.",
        "input_schema": {
            "type": "object",
            "properties": {"kind": {"type": "string", "enum": ["stuck", "approval", "needs_information"]},
                           "reason": {"type": "string", "description": "What you need the human to do, and why."}},
            "required": ["kind", "reason"],
        },
    },
    {
        "name": "finish",
        "description": "End the run.",
        "input_schema": {
            "type": "object",
            "properties": {"status": {"type": "string", "enum": ["success", "impossible"]},
                           "summary": {"type": "string"}},
            "required": ["status", "summary"],
        },
    },
]
