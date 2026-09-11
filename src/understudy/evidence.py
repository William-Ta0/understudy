"""Evidence for a run: a structured, redacted event log plus masked screenshots and UI maps.

    <run dir>/
      events.jsonl     one JSON object per line: seq, ts, actor, type, data. Redacted at write time.
      screens/*.png    screenshots with pii/financial/secret regions blacked out before capture
      ui/*.txt         the text UI map the model (or the engine) saw at that moment, redacted
      result.json      the run result (outputs redacted to placeholders + fingerprints)
      trace.json       discovery only: the structured trace the compiler consumed
      report.md        human-readable timeline

Redaction happens on the way in, so nothing sensitive ever reaches disk, not even briefly.
"""

from __future__ import annotations

import json
import secrets
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .safety.redact import Redactor
from .schema import Model


def new_run_id(kind: str) -> str:
    return f"{kind[:3]}-{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


class Evidence:
    def __init__(self, root: Path, kind: str, label: str, redactor: Redactor, *, run_id: str | None = None):
        self.run_id = run_id or new_run_id(kind)
        self.kind = kind
        self.redactor = redactor
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.dir = root / f"{stamp}-{kind}-{label}"
        n = 2
        while self.dir.exists():
            self.dir = root / f"{stamp}-{kind}-{label}-{n}"
            n += 1
        (self.dir / "screens").mkdir(parents=True)
        (self.dir / "ui").mkdir()
        self._log = open(self.dir / "events.jsonl", "a", encoding="utf-8")
        self._seq = 0
        self._shots = 0
        self._t0 = time.monotonic()
        self.listeners: list[Callable[[dict[str, Any]], None]] = []

    def event(self, type_: str, actor: str = "system", **data: Any) -> dict[str, Any]:
        self._seq += 1
        rec = {
            "seq": self._seq,
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "t": round(time.monotonic() - self._t0, 3),
            "run_id": self.run_id,
            "actor": actor,
            "type": type_,
        }
        for k, v in self.redactor.obj(_jsonable(data)).items():
            rec[f"data_{k}" if k in rec else k] = v  # never let a payload key overwrite the envelope
        self._log.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._log.flush()
        for fn in self.listeners:
            try:
                fn(rec)
            except Exception:  # a broken listener must not break the run
                pass
        return rec

    async def screenshot(self, surface: Any, label: str, *, mask: list[str] | None = None) -> str | None:
        self._shots += 1
        rel = f"screens/{self._shots:03d}-{label}.png"
        try:
            await surface.screenshot(str(self.dir / rel), mask=mask if mask is not None else ["pii", "financial", "secret"])
        except Exception as e:  # e.g. a native dialog is open
            self.event("screenshot_skipped", label=label, reason=str(e)[:200])
            return None
        return rel

    def ui_map(self, label: str, text: str) -> str:
        rel = f"ui/{self._seq:04d}-{label}.txt"
        (self.dir / rel).write_text(self.redactor.text(text), encoding="utf-8")
        return rel

    def write_json(self, name: str, obj: Any, *, redact: bool = True) -> Path:
        data = obj.dump() if isinstance(obj, Model) else obj
        data = self.redactor.obj(_jsonable(data)) if redact else _jsonable(data)
        p = self.dir / name
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return p

    def write_text(self, name: str, text: str) -> Path:
        p = self.dir / name
        p.write_text(self.redactor.text(text), encoding="utf-8")
        return p

    def close(self) -> None:
        self._log.close()


def _jsonable(x: Any) -> Any:
    if isinstance(x, Model):
        return x.dump()
    if isinstance(x, dict):
        return {str(k): _jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, set)):
        return [_jsonable(v) for v in x]
    if isinstance(x, datetime):
        return x.isoformat()
    if isinstance(x, Path):
        return str(x)
    if hasattr(x, "value") and hasattr(x, "name") and type(x).__module__ != "builtins":  # enums
        return x.value
    return x
