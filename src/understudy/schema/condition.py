"""A small, declarative condition language for checkpoints, screens, and runtime conditions.

Conditions are data, not code, so a reviewer can read them and the same definitions
work on any surface that implements `text`, `element`, and `url` checks.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .base import Model, Scope, Text
from .target import Target


class TextCondition(Model):
    """Visible text is present in the scope. A bare string matches as `contains`."""

    kind: Literal["text"] = "text"
    text: Text
    within: list[Scope] = Field(default_factory=list)


class ElementCondition(Model):
    kind: Literal["element"] = "element"
    target: Target
    state: Literal["visible", "absent"] = "visible"


class UrlCondition(Model):
    """The scoped frame's URL (path + query) matches a glob. Templates like {{inputs.x}} are allowed."""

    kind: Literal["url"] = "url"
    pattern: str
    within: list[Scope] = Field(default_factory=list)


class DialogCondition(Model):
    """A native dialog (alert/confirm/prompt) is open, optionally with a matching message."""

    kind: Literal["dialog"] = "dialog"
    message: Text | None = None


class ScreenCondition(Model):
    """The surface is showing a screen defined in the app profile."""

    kind: Literal["screen"] = "screen"
    screen: str


class AllCondition(Model):
    kind: Literal["all"] = "all"
    of: list[Condition]


class AnyCondition(Model):
    kind: Literal["any"] = "any"
    of: list[Condition]


class NotCondition(Model):
    kind: Literal["not"] = "not"
    of: Condition


Condition = Annotated[
    TextCondition | ElementCondition | UrlCondition | DialogCondition | ScreenCondition | AllCondition | AnyCondition | NotCondition,
    Field(discriminator="kind"),
]

for _m in (AllCondition, AnyCondition, NotCondition):
    _m.model_rebuild()


def summarize(c: Condition) -> str:
    match c:
        case TextCondition():
            v = c.text if isinstance(c.text, str) else c.text.value
            return f'text "{v}"' + (f" in {','.join(map(str, c.within))}" if c.within else "")
        case ElementCondition():
            return f"{'no ' if c.state == 'absent' else ''}element {c.target.description}"
        case UrlCondition():
            return f"url ~ {c.pattern}" + (f" in {','.join(map(str, c.within))}" if c.within else "")
        case DialogCondition():
            return "dialog" + (f' "{c.message if isinstance(c.message, str) else c.message.value}"' if c.message else "")
        case ScreenCondition():
            return f"screen {c.screen}"
        case AllCondition():
            return "all(" + "; ".join(summarize(x) for x in c.of) + ")"
        case AnyCondition():
            return "any(" + "; ".join(summarize(x) for x in c.of) + ")"
        case NotCondition():
            return f"not({summarize(c.of)})"
    return str(c)
