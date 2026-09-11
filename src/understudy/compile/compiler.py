"""Trace -> capability. The compiler is where a transcript of what happened becomes a contract.

What it does, in order:
  1. keeps the procedure: `flow` steps by the agent or a human; drops exploratory steps; turns
     incidental steps into review notes (the app profile's runtime conditions own those);
  2. builds each Target from the locator candidates that were validated *at the moment of the
     action* (unique, and the same element), ranked by robustness, with a stated rationale;
  3. generalises: literal input values become {{inputs.x}} templates; tenant labels are mapped
     back to the vendor's default vocabulary, so the artifact is tenant-neutral;
  4. refuses to write member data: any locator or value containing a known sensitive value (or a
     redaction placeholder) is dropped, and flagged if nothing else identifies the control;
  5. derives checkpoints: screen transitions observed at discovery, plus the agent's assertions;
  6. lints the result into review notes for the human who approves it.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .. import __version__
from ..registry import CapabilityStore
from ..safety.redact import Redactor
from ..schema import (
    AllCondition,
    AppProfile,
    AppRef,
    Capability,
    Condition,
    DescribedTarget,
    DiscoveryInfo,
    Entry,
    OutputSpec,
    Provenance,
    Review,
    ReviewNote,
    Risk,
    ScreenCondition,
    Target,
    TenantBinding,
    Trace,
    TraceStep,
)
from ..schema.target import SEMANTIC

PREFERENCE = ["role", "label", "text", "table_cell", "attr", "css", "point"]
WHY = {
    "role": "role + accessible name: what the operator reads; survives layout and generated-id changes",
    "label": "the label printed next to the field; survives layout changes; tenant relabels go through vocabulary",
    "text": "the control's visible text",
    "table_cell": "a grid value by column header and row key, never by position",
    "attr": "vendor-set attribute (form field name or route); invisible to users, so tenants rarely change it",
    "css": "stable attributes only (no generated ids); last resort",
    "point": "coordinates: fragile, recorded only because nothing else identified the control",
}
_PLACEHOLDER = re.compile(r"\[(pii|financial|secret|ssn|card|email|phone)\b")
VERB = {"click": "click", "fill": "enter", "select": "choose", "press": "press", "dialog": "answer_dialog", "check": "set"}


class CompileError(ValueError):
    def __init__(self, message: str, notes: list[ReviewNote]):
        super().__init__(message)
        self.notes = notes


def _slug(s: str, n: int = 32) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")
    return s[:n].rstrip("_") or "control"


class Compiler:
    def __init__(self, profile: AppProfile, tenant: TenantBinding, redactor: Redactor | None = None):
        self.profile = profile
        self.tenant = tenant
        self.redactor = redactor or Redactor()
        self.inverse_vocab = {v: k for k, v in tenant.vocabulary.items()}

    # ------------------------------------------------------------------ entry point

    def compile(self, trace: Trace, inputs: dict[str, str], store: CapabilityStore | None = None) -> Capability:
        goal = trace.goal
        if not trace.finish or trace.finish.status != "success":
            raise CompileError(f"discovery did not succeed ({trace.finish.status if trace.finish else 'unfinished'})", [])
        self.params = sorted(((v, k) for k, v in inputs.items() if len(v) >= 3), key=lambda x: -len(x[0]))
        self.exact = {v: k for k, v in inputs.items() if v}  # a whole value equal to an input is templated at any length
        self.notes: list[ReviewNote] = []
        steps: list[dict[str, Any]] = []
        outputs: dict[str, dict[str, Any]] = {}
        ids: set[str] = set()
        human_required = {i for iv in trace.interventions if iv.kind == "human_required" for i in iv.human_steps}
        self.asked = {i: iv.reason for iv in trace.interventions for i in iv.human_steps}
        stuck_help = {i for iv in trace.interventions if iv.kind in ("stuck", "takeover") for i in iv.human_steps}

        detours = self._detours(trace)
        inherited_screen: str | None = None
        for p in trace.platform:
            self.note("info", None, f"platform handled runtime condition '{p['condition']}' ({p['action']}) during discovery; "
                                    "replay handles it the same way, so it is not a step")
        for idx, ts in enumerate(trace.steps):
            if not ts.ok:
                self.note("info", None, f"discovery step {ts.index} ({ts.action}) was refused: {ts.error}")
                continue
            if ts.index in human_required:
                self.note("info", None, f"operator step {ts.index} resolved a human_required condition; replay escalates to a human there too")
                continue
            if ts.index in detours:
                self.note("info", None, f"dropped detour step {ts.index} ('{ts.rationale.split(' | ')[0][:70]}'): it led to an "
                                        "unrecognised screen, and the next action replaced that frame's content without using it")
                inherited_screen = ts.screen_before  # the next step really starts from where the detour started
                continue
            if ts.purpose == "exploratory":
                self.note("info", None, f"dropped exploratory step {ts.index}: {ts.rationale[:80]}")
                continue
            if ts.purpose == "incidental":
                self.note("warning", None, f"step {ts.index} was situational ({ts.rationale[:80]}). If this interruption can "
                                           "recur, add it to the app profile as a runtime condition")
                continue
            if ts.action == "checkpoint":
                self._attach_checkpoint(steps, ts)
                continue
            if ts.action == "extract":
                self._extract(steps, outputs, ts, trace, ids)
                continue
            step = self._action_step(ts, trace, idx, ids)
            if step is None:
                continue
            if inherited_screen and "screen" not in step:
                step["screen"] = inherited_screen
            inherited_screen = None
            if ts.actor == "human" and ts.index in stuck_help:
                self.note("warning", step["id"], "demonstrated by a human operator after the agent got stuck; review it closely")
            steps.append(step)

        if not steps:
            raise CompileError("nothing to compile: the trace has no flow steps", self.notes)
        missing = set(goal.outputs) - set(outputs)
        if missing:
            raise CompileError(f"outputs never extracted with a semantic locator: {sorted(missing)}", self.notes)

        risk = max((Risk(s.get("risk", "reversible")) for s in steps), key=lambda r: r.rank)
        success = self._generalize(trace.finish.success.dump()) if trace.finish.success else {"kind": "screen", "screen": steps[-1].get("screen")}
        body = {
            "schema": "understudy/capability@1",
            "id": goal.capability,
            "version": "1.0.0",
            "title": goal.title,
            "description": self.redactor.text(goal.goal),
            "status": "draft",
            "app": AppRef(product=self.profile.product, profile=self.profile.id, versions=self.profile.versions).dump(),
            "inputs": {k: v.dump() for k, v in goal.inputs.items()},
            "outputs": outputs,
            "outcomes": [o.dump() for o in goal.outcomes],
            "entry": Entry(screen=goal.entry).dump(),
            "steps": steps,
            "success": success,
            "risk": risk.value,
            "provenance": Provenance(
                discovered=DiscoveryInfo(
                    run_id=trace.run_id, goal=self.redactor.text(goal.goal), model=trace.llm.model if trace.llm else "unknown",
                    tenant=trace.tenant, product_version=trace.product_version, at=trace.started_at,
                    agent_steps=sum(1 for s in trace.steps if s.actor == "agent"),
                    human_steps=sum(1 for s in trace.steps if s.actor == "human"),
                    llm_calls=trace.llm.calls if trace.llm else 0),
                compiled_by=f"understudy {__version__}",
                trace_digest="sha256:" + hashlib.sha256(json.dumps(trace.dump(), sort_keys=True).encode()).hexdigest(),
            ).dump(),
            "review": Review().dump(),
        }
        for o in goal.outcomes:
            try:
                self.profile.condition(o.condition)
            except KeyError:
                self.note("blocker", None, f"outcome {o.code} maps to unknown runtime condition '{o.condition}'")
        cap = Capability.model_validate(body)
        self._lint(cap)
        cap = cap.model_copy(update={"review": Review(notes=self.notes)})
        if store is not None:
            cap = cap.model_copy(update={"version": store.next_version(cap)})
        return cap

    @staticmethod
    def _detours(trace: Trace) -> set[int]:
        """Navigation whose result was thrown away, like a dead store: step k opened an unrecognised
        screen in frame F, and the next action happened elsewhere and loaded new content into F."""
        acts = [s for s in trace.steps if s.actor == "agent" and s.ok and s.action in ("click", "fill", "select", "press")]
        out: set[int] = set()
        for k, n in zip(acts, acts[1:]):
            if k.action != "click" or k.purpose != "flow" or k.screen_after is not None or not k.frames_before:
                continue
            changed_k = {f for f, u in k.frames_after.items() if k.frames_before.get(f) != u}
            changed_n = {f for f, u in n.frames_after.items() if n.frames_before.get(f) != u}
            if changed_k and n.target is not None and n.target.frame not in changed_k and changed_k <= changed_n:
                out.add(k.index)
        return out

    def note(self, level: str, step: str | None, message: str) -> None:
        self.notes.append(ReviewNote(level=level, step=step, message=self.redactor.text(message)))  # type: ignore[arg-type]

    # ------------------------------------------------------------------ steps

    def _unique_id(self, base: str, ids: set[str]) -> str:
        sid, n = base, 2
        while sid in ids:
            sid, n = f"{base}_{n}", n + 1
        ids.add(sid)
        return sid

    def _intent(self, ts: TraceStep) -> str:
        intent = ts.rationale.split(" | ")[0].strip() if ts.rationale else ""
        if ts.actor == "human" and (not intent or intent.startswith("operator")):
            what = f'{ts.action} {ts.target.role} "{ts.target.name or ts.target.label or ts.target.text[:40]}"' if ts.target else ts.action
            asked = self.asked.get(ts.index)
            if asked and len(asked) > 160:
                asked = asked[:157].rsplit(" ", 1)[0] + "..."
            intent = f"Human operator: {what}" + (f" (asked for: {asked})" if asked else "")
        return self._generalize_text(self.redactor.text(intent or ts.action))

    def _screen_after(self, trace: Trace, idx: int, ts: TraceStep) -> str | None:
        """The screen the action led to. The next observation is authoritative: by then the app has settled."""
        for later in trace.steps[idx + 1:]:
            if later.actor == "agent" and later.screen_before:
                return later.screen_before
        return ts.screen_after

    def _action_step(self, ts: TraceStep, trace: Trace, idx: int, ids: set[str]) -> dict[str, Any] | None:
        action = ts.action
        if action not in ("click", "fill", "select", "press", "dialog"):
            self.note("warning", None, f"step {ts.index}: action '{action}' is not compiled")
            return None
        if (action == "fill" and ts.value == "[secret]") or (ts.target is not None and ts.target.sensitive == "secret"):
            self.note("blocker", None, f"step {ts.index} typed a secret. Secrets never go into artifacts: model this screen as a "
                                       "human_required runtime condition in the app profile")
            return None
        step: dict[str, Any] = {"action": action, "intent": self._intent(ts), "origin": ts.actor}
        if ts.screen_before:
            step["screen"] = ts.screen_before
        label = ""
        if action == "dialog":
            step["response"] = "accept" if ts.value == "accept" else "dismiss"
        elif action == "press" and ts.target is None:
            step["key"] = ts.value or "Enter"
        else:
            if ts.target is None:
                self.note("blocker", None, f"step {ts.index}: no target was captured")
                return None
            target = self._target(ts.target, where=f"step {ts.index}")
            if target is None:
                return None
            step["target"] = target
            label = ts.target.label or ts.target.name or ts.target.text
            if action == "fill":
                step["value"] = self._value(ts.value or "", f"step {ts.index}")
            elif action == "select":
                step["option"] = self._option(ts, f"step {ts.index}")
            elif action == "press":
                step["key"] = ts.value or "Enter"
        step["id"] = self._unique_id(f"{VERB.get(action, action)}_{_slug(self._generalize_text(label))}", ids)
        step["risk"] = ts.risk.value
        if ts.risk == Risk.irreversible:
            step["approval"] = "required"
        after = self._screen_after(trace, idx, ts)
        if after and after != ts.screen_before and action in ("click", "press", "dialog"):
            step["expect"] = {"kind": "screen", "screen": after}
        return step

    def _attach_checkpoint(self, steps: list[dict[str, Any]], ts: TraceStep) -> None:
        cond = self._generalize(ts.checkpoint.dump()) if ts.checkpoint else None
        target = next((s for s in reversed(steps) if s["action"] in ("click", "press", "dialog")), None)
        if cond is None:
            return
        if target is None:
            self.note("info", None, f"checkpoint '{ts.rationale[:60]}' precedes any action; it is covered by the entry screen")
            return
        prev = target.get("expect")
        target["expect"] = {"kind": "all", "of": [prev, cond]} if prev else cond

    def _extract(self, steps: list[dict[str, Any]], outputs: dict[str, dict[str, Any]], ts: TraceStep, trace: Trace,
                 ids: set[str]) -> None:
        name = ts.output or ""
        decl = trace.goal.outputs.get(name)
        if decl is None or ts.target is None:
            return
        source = self._target(ts.target, where=f"output {name}", semantic_only=True)
        if source is None:
            self.note("blocker", None, f"output '{name}' has no semantic locator")
            return
        outputs[name] = OutputSpec(type=decl.type, description=decl.description, sensitivity=decl.sensitivity,
                                   source=Target.model_validate(source), pattern=decl.pattern).dump()
        last = steps[-1] if steps else None
        if last and last["action"] == "extract" and last.get("screen") == ts.screen_before:
            if name not in last["outputs"]:
                last["outputs"].append(name)
            return
        step = {"id": self._unique_id(f"read_{_slug(ts.screen_before or 'outputs')}", ids), "action": "extract",
                "intent": "Read the declared outputs from the screen", "outputs": [name], "risk": "read", "origin": ts.actor}
        if ts.screen_before:
            step["screen"] = ts.screen_before
        steps.append(step)

    # ------------------------------------------------------------------ targets & generalisation

    def _target(self, dt: DescribedTarget, *, where: str, semantic_only: bool = False) -> dict[str, Any] | None:
        valid = [c for c in dt.candidates if c.unique and c.same and c.locator.get("by") in PREFERENCE]
        valid.sort(key=lambda c: PREFERENCE.index(c.locator["by"]))
        locs: list[dict[str, Any]] = []
        dropped_sensitive = False
        for c in valid:
            by = c.locator["by"]
            if semantic_only and by not in SEMANTIC:
                continue
            loc = self._generalize(dict(c.locator))
            if self._has_sensitive(loc):
                dropped_sensitive = True
                continue
            loc["why"] = WHY[by]
            if loc not in locs:
                locs.append(loc)
        if not locs:
            reason = "every locator contained member data" if dropped_sensitive else "no locator identified it uniquely"
            self.note("blocker", None, f"{where}: cannot build a target ({reason})")
            return None
        if dropped_sensitive:
            self.note("info", None, f"{where}: locators that contained member data were dropped")
        locs = locs[:4]
        if locs[0]["by"] not in SEMANTIC:
            self.note("warning", None, f"{where}: no semantic locator; primary is '{locs[0]['by']}'")
        if any(loc["by"] == "point" for loc in locs):
            self.note("warning", None, f"{where}: uses a coordinate locator")
        primary = locs[0]
        frame = f" in the {dt.frame} frame" if dt.frame and dt.frame != "top" else ""
        if primary["by"] == "table_cell":
            key = ", ".join(f"{k} = {v}" for k, v in primary["row"].items())
            desc = f'"{primary["column"]}" cell of the row where {key}{frame}'
        elif primary["by"] == "label" and primary.get("role") == "cell":
            desc = f'value next to the label "{primary["label"]}"{frame}'
        else:
            shown = self._generalize_text(dt.label or dt.name or dt.text[:40])
            if self._has_sensitive(shown):
                shown = "(member data)"
            desc = f'{dt.role} "{shown}"{frame}'
        within = [{"frame": dt.frame}] if dt.frame and dt.frame != "top" else []
        return {"description": desc, "within": within, "locators": locs}

    def _has_sensitive(self, x: Any) -> bool:
        s = json.dumps(x) if not isinstance(x, str) else x
        return bool(_PLACEHOLDER.search(s)) or self.redactor.text(s) != s

    def _generalize_text(self, s: str) -> str:
        if s in self.inverse_vocab:
            s = self.inverse_vocab[s]
        for literal, name in self.params:
            if literal in s:  # whole tokens only: "100234" must not match inside "$1,002,345.00"
                s = re.sub(rf"(?<![\w.,$]){re.escape(literal)}(?![\w])", f"{{{{inputs.{name}}}}}", s)
        return s

    def _generalize(self, x: Any) -> Any:
        if isinstance(x, str):
            return self._generalize_text(x)
        if isinstance(x, dict):
            return {self._generalize_text(k) if isinstance(k, str) else k: self._generalize(v) for k, v in x.items()}
        if isinstance(x, list):
            return [self._generalize(v) for v in x]
        return x

    def _option(self, ts: TraceStep, where: str) -> str:
        """Prefer a template; then the option's underlying value when its label carries volatile data
        (e.g. "00 - Share Savings ($25,310.77 avail)"); a plain label last."""
        label, val = ts.value or "", ts.option_value
        for candidate in (label, val):
            if candidate and candidate in self.exact:
                return f"{{{{inputs.{self.exact[candidate]}}}}}"
        g = self._generalize_text(label)
        if "{{" in g and not self._has_sensitive(g):
            return g
        if val:
            gv = self._generalize_text(val)
            if gv != val or self._has_sensitive(label) or label.startswith("["):
                if gv == val:
                    self.note("warning", None, f"{where}: selects the option with value '{val}' (its label shows member data)")
                return gv
        return self._value(label, where)

    def _value(self, v: str, where: str) -> str:
        if v in self.exact:
            return f"{{{{inputs.{self.exact[v]}}}}}"
        g = self._generalize_text(v)
        if "{{" not in g:
            if self._has_sensitive(g):
                self.note("blocker", None, f"{where}: a literal sensitive value was typed; it was not recorded")
                return "{{inputs.MISSING}}"
            self.note("warning", None, f"{where}: types the literal constant '{g}'. If it varies per call, make it an input")
        return g

    # ------------------------------------------------------------------ lint

    def _lint(self, cap: Capability) -> None:
        for s in cap.steps:
            if s.screen is None and s.origin != "human":
                self.note("warning", s.id, "no precondition screen: the app profile did not recognise the screen at discovery")
            if s.origin == "human":
                self.note("info", s.id, "performed by a human operator at discovery")
            if s.risk == Risk.irreversible:
                self.note("info", s.id, "irreversible: replay pauses for a human approval before this step")
            if s.action == "click" and s.expect is None:
                self.note("info", s.id, "no checkpoint after this click (the screen did not change at discovery)")
        if not cap.outcomes:
            self.note("warning", None, "no business outcomes declared; unmapped business conditions surface with profile codes")


def success_screen(cond: Condition) -> str | None:
    if isinstance(cond, ScreenCondition):
        return cond.screen
    if isinstance(cond, AllCondition):
        return next((c.screen for c in cond.of if isinstance(c, ScreenCondition)), None)
    return None
