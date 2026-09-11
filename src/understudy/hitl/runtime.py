"""Run the operator console (and optionally a simulated operator) next to the automation."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn

from .console import create_console
from .control import ControlCenter, InterventionRouter
from .operator_sim import run_operator

log = logging.getLogger(__name__)


@asynccontextmanager
async def operator_console(router: InterventionRouter, *, port: int = 8766,
                           operator_script: Path | None = None) -> AsyncIterator[ControlCenter]:
    base = f"http://127.0.0.1:{port}"
    center = ControlCenter(router, console_base=base)
    server = uvicorn.Server(uvicorn.Config(create_console(center), host="127.0.0.1", port=port, log_level="warning"))
    serve = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)
    sim = asyncio.create_task(run_operator(base, center.token, operator_script)) if operator_script else None
    center.operator_task = sim  # type: ignore[attr-defined]
    try:
        yield center
    finally:
        if sim is not None:
            if not sim.done():
                sim.cancel()
            elif sim.exception() is not None:
                log.error("operator script failed: %s", sim.exception())
        server.should_exit = True
        await serve
