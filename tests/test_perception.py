"""Perception on a hostile legacy surface: frames, unlabeled table-layout fields, <td onclick> menus, grids."""

from __future__ import annotations

import pytest

from understudy.registry import load_tenant
from understudy.schema import Target
from understudy.surface.web import WebSurface

pytestmark = pytest.mark.browser


async def _signed_in(mock) -> WebSurface:
    s = await WebSurface.launch()
    base = load_tenant("lakeshore").base_url
    await s.goto(f"{base}/signon.asp")
    await s.page.fill("input[name=uid]", "tlr_demo")
    await s.page.fill("input[name=pwd]", "keystone-demo")
    await s.page.click("input[type=submit]")
    await s.settle()
    return s


def _target(within: str, *locs: dict) -> Target:
    return Target.model_validate({"description": "t", "within": [{"frame": within}], "locators": list(locs)})


async def test_menu_cells_and_table_layout_labels(mock):
    s = await _signed_in(mock)
    try:
        obs = await s.observe()
        nav = obs.frame("nav")
        menu = next(n for n in nav.nodes if n.get("name") == "Member Inquiry")
        assert menu["role"] == "button" and menu.get("inferred")  # a <td onclick>, not a link
        res = await s.resolve(_target("nav", {"by": "role", "role": "button", "name": "Member Inquiry"}))
        await s.click(res)
        await s.settle()
        obs = await s.observe()
        box = next(n for n in obs.frame("main").nodes if n["role"] == "textbox" and n["attrs"].get("name") == "txtMbrNo")
        assert box["label"] == "Member Number" and box["name"] == ""  # no <label>: the label comes from the cell to the left
    finally:
        await s.close()


async def test_grid_values_resolve_by_header_and_row_key(mock):
    s = await _signed_in(mock)
    try:
        await s.click(await s.resolve(_target("nav", {"by": "role", "role": "button", "name": "Member Inquiry"})))
        await s.settle()
        await s.fill(await s.resolve(_target("main", {"by": "label", "role": "textbox", "label": "Member Number"})), "100234")
        await s.click(await s.resolve(_target("main", {"by": "role", "role": "button", "name": "Search"})))
        await s.settle()
        cell = await s.resolve(_target("main", {"by": "table_cell", "headers": ["Description", "Current Balance"],
                                               "row": {"Description": "Share Savings"}, "column": "Current Balance"}))
        assert cell.found and (await s.read(cell))["text"] == "$2,431.18"
        # the recorder's candidates for that cell are validated live: unique and the same element
        obs = await s.observe()
        node = next(n for n in obs.frame("main").nodes if n["text"] == "$2,431.18")
        assert node["sensitive"] == "financial"
        desc = await s.describe_ref(node["ref"])
        good = [c for c in desc["candidates"] if c["unique"] and c["same"]]
        assert good[0]["locator"]["by"] == "table_cell"
        # member data is tagged so screenshots and the model's view can mask it
        name = next(n for n in obs.frame("main").nodes if n["text"] == "DANA R WHITFIELD")
        assert name["sensitive"] == "pii"
    finally:
        await s.close()


async def test_generated_ids_are_never_used_as_locators(mock):
    s = await _signed_in(mock)
    try:
        await s.click(await s.resolve(_target("nav", {"by": "role", "role": "button", "name": "Member Inquiry"})))
        await s.settle()
        obs = await s.observe()
        box = next(n for n in obs.frame("main").nodes if n["role"] == "textbox" and n["label"] == "Member Number")
        desc = await s.describe_ref(box["ref"])
        assert "ctl00_" not in str(desc["candidates"])
    finally:
        await s.close()
