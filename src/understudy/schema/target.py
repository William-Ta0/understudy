"""How a recorded step identifies the control it acts on.

A `Target` is a scope chain plus an ordered list of `Locator`s. Each locator is an
independent way to find the same control, ranked by how well it survives change:

    role / label / text   what the operator sees. Survives layout changes, generated ids, and
                          vendor re-skins. Breaks when a tenant relabels a field.
    table_cell            a grid value by column header and row key, the way a human reads a
                          table. Never positional.
    attr                  non-visual attributes set by the vendor (form field `name`, a route in
                          an onclick). Invisible to users, so tenants rarely change them.
    css                   built from stable attributes only (never generated ids). Last resort.
    point                 coordinates inside the scope, for surfaces with no element tree
                          (Citrix, canvas). Flagged for review whenever it is recorded.

Replay tries locators in order and takes the first that matches exactly one visible
element. Using anything but the first is reported as locator drift. Reads (outputs) only
ever use semantic locators, because a wrong read returns wrong data with no error.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from .base import Model, Scope, Text


class _LocatorBase(Model):
    nth: int | None = Field(default=None, description="0-based pick among multiple matches. Discouraged; flagged in review.")
    why: str | None = Field(default=None, description="Why this locator is expected to be stable (written by the compiler).")


class RoleLocator(_LocatorBase):
    by: Literal["role"] = "role"
    role: str
    name: Text


class LabelLocator(_LocatorBase):
    """A control found by the label text a human reads next to it (or a value cell by its row label)."""

    by: Literal["label"] = "label"
    label: Text
    role: str | None = None


class TextLocator(_LocatorBase):
    by: Literal["text"] = "text"
    text: Text
    role: str | None = None


class TableCellLocator(_LocatorBase):
    """A data cell: the table is identified by its header texts, the row by key column values."""

    by: Literal["table_cell"] = "table_cell"
    headers: list[str]
    row: dict[str, Text]
    column: str


class AttrLocator(_LocatorBase):
    by: Literal["attr"] = "attr"
    tag: str | None = None
    attrs: dict[str, Text]


class CssLocator(_LocatorBase):
    by: Literal["css"] = "css"
    css: str


class PointLocator(_LocatorBase):
    by: Literal["point"] = "point"
    x: int
    y: int


Locator = Annotated[
    RoleLocator | LabelLocator | TextLocator | TableCellLocator | AttrLocator | CssLocator | PointLocator,
    Field(discriminator="by"),
]

SEMANTIC = {"role", "label", "text", "table_cell"}


class Target(Model):
    description: str = Field(description="Human-readable description, e.g. 'textbox \"Member Number\" in main frame'.")
    within: list[Scope] = Field(default_factory=list)
    locators: list[Locator] = Field(min_length=1)

    @property
    def primary(self) -> Locator:
        return self.locators[0]


def describe_locator(loc: Locator) -> str:
    """One-line human summary, used in logs and drift reports."""

    def t(v: Text) -> str:
        return v if isinstance(v, str) else f"{v.mode}:{v.value}"

    match loc:
        case RoleLocator():
            s = f'role={loc.role} name="{t(loc.name)}"'
        case LabelLocator():
            s = f'label="{t(loc.label)}"' + (f" role={loc.role}" if loc.role else "")
        case TextLocator():
            s = f'text="{t(loc.text)}"' + (f" role={loc.role}" if loc.role else "")
        case TableCellLocator():
            key = ", ".join(f"{k}={t(v)}" for k, v in loc.row.items())
            s = f'table_cell column="{loc.column}" row[{key}]'
        case AttrLocator():
            s = "attr " + " ".join(f"{k}={t(v)}" for k, v in loc.attrs.items())
        case CssLocator():
            s = f"css {loc.css}"
        case PointLocator():
            s = f"point ({loc.x},{loc.y})"
        case _:
            s = str(loc)
    return s + (f" nth={loc.nth}" if loc.nth is not None else "")
