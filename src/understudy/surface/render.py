"""Text rendering of an observation: the "UI map" the model reads and the evidence stores.

Nodes carry refs the model acts on (`[m8] button "Search"`). Values tagged with a masked
sensitivity are replaced by their kind, so the model and the evidence store see the
structure of a screen without its member data.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from .base import Observation

_TOKENISH = re.compile(r"(?<=[=])[0-9a-f]{8,}(?=&|$)", re.I)


def short_url(url: str) -> str:
    p = urlsplit(url)
    q = _TOKENISH.sub("…", p.query)
    return p.path + (f"?{q}" if q else "")


def _q(s: str, n: int = 90) -> str:
    s = " ".join((s or "").split())
    return '"' + (s[: n - 1] + "…" if len(s) > n else s) + '"'


def render_node(n: dict, mask: set[str]) -> str:
    sens = n.get("sensitive")
    hidden = sens in mask
    role = n["role"]
    parts = [f"[{n['ref']}]", role]
    label = n.get("label") or ""
    name = n.get("name") or ""
    text = n.get("text") or ""
    if role in ("textbox", "combobox", "checkbox", "radio"):
        parts.append(_q(label or name) if (label or name) else '""')
        if "value" in n:
            parts.append(f"value=[{sens}]" if hidden and n["value"] else f"value={_q(n['value'], 40)}")
        if "checked" in n:
            parts.append("checked" if n["checked"] else "unchecked")
        if n.get("options"):
            opts = [o["label"] for o in n["options"]]
            sel = next((o["label"] for o in n["options"] if o.get("selected")), None)
            parts.append("options=[" + ", ".join(_q(o, 40) for o in opts[:15]) + (", …" if len(opts) > 15 else "") + "]")
            if sel is not None:
                parts.append(f"selected={_q(sel, 40)}")
    elif role in ("button", "link"):
        parts.append(_q(name or text))
        if n.get("inferred"):
            parts.append(f"(clickable <{n['tag']}>)")
    else:
        parts.append(f"[{sens}]" if hidden else _q(text, 120))
    cell = n.get("cell")
    if cell and not cell.get("isHeader") and cell.get("header"):
        parts.append(f"(column {_q(cell['header'], 30)}, row {_q(cell.get('rowKey', ''), 30)})")
    if n.get("disabled"):
        parts.append("disabled")
    if n.get("emphasis") == "error":
        parts.append("(!error)")
    return " ".join(parts)


def render_observation(obs: Observation, *, mask: set[str] | None = None, max_nodes: int = 260) -> str:
    mask = mask or set()
    lines: list[str] = []
    if obs.dialog:
        lines.append(f"== NATIVE DIALOG ({obs.dialog.get('type')}) is open and blocks the page: {_q(obs.dialog.get('message', ''), 200)}")
        lines.append("   Respond with handle_dialog(accept=true|false). Nothing else can be read or clicked until then.")
    for u in obs.blocked:
        lines.append(f"!! request blocked by policy: {short_url(u)}")
    budget = max_nodes
    for f in obs.frames:
        if not f.nodes:
            continue
        lines.append(f'== frame "{f.key}" · {short_url(f.url)} · {_q(f.title, 60)}')
        for n in f.nodes:
            if budget <= 0:
                lines.append("   … (truncated)")
                break
            lines.append("  " + render_node(n, mask))
            budget -= 1
    return "\n".join(lines)
