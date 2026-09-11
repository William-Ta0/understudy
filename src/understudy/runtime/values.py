"""Typed values: validating caller inputs, rendering templates, and parsing outputs read off the screen."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from ..schema import Model, ParamSpec, ValueType

TEMPLATE_RE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


class InputError(ValueError):
    def __init__(self, problems: dict[str, str]):
        super().__init__("; ".join(f"{k}: {v}" for k, v in problems.items()))
        self.problems = problems


def _to_decimal(raw: str) -> Decimal:
    s = raw.strip().replace("$", "").replace(",", "")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    d = Decimal(s)
    return -d if neg else d


def coerce_input(name: str, spec: ParamSpec, raw: Any) -> str:
    """Validate one input and return its canonical string form (what gets typed into the UI)."""
    s = str(raw).strip()
    t = spec.type
    if t in (ValueType.money, ValueType.decimal):
        try:
            d = _to_decimal(s)
        except InvalidOperation:
            raise ValueError("not a number") from None
        if spec.minimum is not None and d < spec.minimum:
            raise ValueError(f"below minimum {spec.minimum}")
        if spec.maximum is not None and d > spec.maximum:
            raise ValueError(f"above maximum {spec.maximum}")
        s = f"{d:.2f}" if t == ValueType.money else str(d)
    elif t == ValueType.integer:
        if not re.fullmatch(r"-?\d+", s):
            raise ValueError("not an integer")
    elif t == ValueType.date:
        try:
            s = date.fromisoformat(s).isoformat()
        except ValueError:
            raise ValueError("not an ISO date (YYYY-MM-DD)") from None
    elif t == ValueType.boolean:
        if s.lower() not in ("true", "false", "yes", "no", "1", "0"):
            raise ValueError("not a boolean")
        s = "true" if s.lower() in ("true", "yes", "1") else "false"
    elif t == ValueType.enum:
        match = next((v for v in spec.enum or [] if v.lower() == s.lower()), None)
        if match is None:
            raise ValueError(f"must be one of {spec.enum}")
        s = match
    if spec.pattern and not re.fullmatch(spec.pattern, s):
        raise ValueError(f"does not match pattern {spec.pattern}")
    return s


def validate_inputs(specs: dict[str, ParamSpec], given: dict[str, Any]) -> dict[str, str]:
    problems: dict[str, str] = {}
    out: dict[str, str] = {}
    for k in given:
        if k not in specs:
            problems[k] = "unknown input"
    for k, spec in specs.items():
        if k not in given or given[k] in (None, ""):
            if spec.required:
                problems[k] = "required"
            continue
        try:
            out[k] = coerce_input(k, spec, given[k])
        except ValueError as e:
            problems[k] = str(e)
    if problems:
        raise InputError(problems)
    return out


class Renderer:
    """Renders {{inputs.x}}, {{tenant.x}}, {{secrets.x}} templates. Unknown names are errors, never blanks."""

    def __init__(self, inputs: dict[str, str] | None = None, tenant: dict[str, str] | None = None,
                 secrets: dict[str, str] | None = None):
        self.scopes: dict[str, dict[str, str]] = {"inputs": inputs or {}, "tenant": tenant or {}, "secrets": secrets or {}}

    def __call__(self, s: str) -> str:
        def sub(m: re.Match[str]) -> str:
            scope, _, key = m.group(1).partition(".")
            if scope not in self.scopes or key not in self.scopes[scope]:
                raise KeyError(f"unresolved template {{{{{m.group(1)}}}}}")
            return self.scopes[scope][key]

        return TEMPLATE_RE.sub(sub, s)

    def render_obj(self, obj: Any) -> Any:
        if isinstance(obj, str):
            return self(obj)
        if isinstance(obj, dict):
            return {self(k) if isinstance(k, str) else k: self.render_obj(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.render_obj(v) for v in obj]
        return obj

    def render_model(self, m: Model) -> Any:
        return type(m).model_validate(self.render_obj(m.dump()))


def parse_output(t: ValueType, raw: str, pattern: str | None = None) -> Any:
    """Parse text read off the screen into the declared type. Money/decimal return strings to keep precision."""
    s = " ".join(raw.split())
    if pattern and not re.search(pattern, s):
        raise ValueError(f"{s!r} does not match {pattern}")
    if t in (ValueType.money, ValueType.decimal):
        try:
            d = _to_decimal(s)
        except InvalidOperation:
            raise ValueError(f"{s!r} is not a number") from None
        return f"{d:.2f}" if t == ValueType.money else str(d)
    if t == ValueType.integer:
        return int(s.replace(",", ""))
    if t == ValueType.date:
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%d-%b-%Y"):
            try:
                return datetime.strptime(s, fmt).date().isoformat()
            except ValueError:
                continue
        raise ValueError(f"{s!r} is not a recognised date")
    if t == ValueType.boolean:
        return s.lower() in ("yes", "y", "true", "1", "on")
    if not s:
        raise ValueError("empty")
    return s
