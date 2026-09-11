"""Model clients for discovery. Replay never imports this module.

Each decision is one stateless request: the system prompt and tool list are fixed (so
they cache), and the user turn carries the goal, a compact history, and the current
screen. The loop owns memory; the model gets exactly what it needs for one decision.
That keeps context bounded and makes every decision independently auditable.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from ..surface.base import Observation


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class Decision:
    calls: list[ToolCall]
    text: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    stop_reason: str = ""


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    model: str

    async def decide(self, system: str, text: str, image_png: bytes | None, tools: list[dict[str, Any]],
                     observation: Observation | None = None) -> Decision: ...


# --------------------------------------------------------------------------- Anthropic


class AnthropicLLM:
    """Claude via the official SDK. Server-side refusal fallbacks are enabled by default."""

    def __init__(self, model: str | None = None, effort: str | None = None, fallbacks: bool = True):
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.AsyncAnthropic(max_retries=3)
        self.model = model or os.environ.get("UNDERSTUDY_MODEL", "claude-opus-5")
        self.effort = effort or os.environ.get("UNDERSTUDY_EFFORT")
        self.fallbacks = fallbacks and os.environ.get("UNDERSTUDY_FALLBACKS", "1") != "0"

    async def decide(self, system: str, text: str, image_png: bytes | None, tools: list[dict[str, Any]],
                     observation: Observation | None = None) -> Decision:
        content: list[dict[str, Any]] = []
        if image_png:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                         "data": base64.standard_b64encode(image_png).decode()}})
        content.append({"type": "text", "text": text})
        extra: dict[str, Any] = {}
        betas: list[str] = []
        if self.fallbacks:
            extra["fallbacks"] = "default"
            betas.append("server-side-fallback-2026-07-01")
        if self.effort:
            extra["output_config"] = {"effort": self.effort}
        anthropic = self._anthropic
        try:
            resp = await self.client.beta.messages.create(
                model=self.model,
                max_tokens=16000,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                tools=tools,
                tool_choice={"type": "auto", "disable_parallel_tool_use": True},
                messages=[{"role": "user", "content": content}],
                betas=betas,
                extra_body=extra or None,
            )
        except anthropic.BadRequestError as e:
            raise LLMError(f"bad request: {e.message}") from e
        except anthropic.AuthenticationError as e:
            raise LLMError("authentication failed: check ANTHROPIC_API_KEY") from e
        except anthropic.RateLimitError as e:
            raise LLMError("rate limited after retries") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise LLMError(f"connection error: {e}") from e
        if resp.stop_reason == "refusal":
            raise LLMError("the model declined this request (stop_reason=refusal)")
        calls, texts = [], []
        for block in resp.content:
            if block.type == "tool_use":
                calls.append(ToolCall(id=block.id, name=block.name, args=dict(block.input or {})))
            elif block.type == "text":
                texts.append(block.text)
        u = resp.usage
        usage = {"input_tokens": u.input_tokens, "output_tokens": u.output_tokens,
                 "cache_read_tokens": getattr(u, "cache_read_input_tokens", 0) or 0}
        return Decision(calls=calls, text="\n".join(texts).strip(), usage=usage, stop_reason=resp.stop_reason or "")


# --------------------------------------------------------------------------- OpenAI-compatible


class OpenAICompatLLM:
    """Any OpenAI-compatible chat-completions endpoint (OpenAI, OpenRouter, Zhipu GLM, vLLM, ...)."""

    def __init__(self, model: str | None = None):
        try:
            import openai
        except ImportError as e:  # optional dependency
            raise LLMError("install the 'openai' extra: uv sync --extra openai") from e
        self._openai = openai
        # Cross-region endpoints behind proxies can take seconds just for the TLS handshake.
        self.client = openai.AsyncOpenAI(base_url=os.environ.get("OPENAI_BASE_URL") or None, max_retries=3,
                                         timeout=openai.Timeout(180.0, connect=30.0))
        self.model = model or os.environ.get("UNDERSTUDY_MODEL", "gpt-4.1")
        # Text-only models get the UI map alone; the policy may allow screenshots, the model may not take them.
        self.vision = os.environ.get("UNDERSTUDY_VISION", "1") != "0"

    async def decide(self, system: str, text: str, image_png: bytes | None, tools: list[dict[str, Any]],
                     observation: Observation | None = None) -> Decision:
        parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
        if image_png and self.vision:
            b64 = base64.standard_b64encode(image_png).decode()
            parts.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
        fns = [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                                  "parameters": t["input_schema"]}} for t in tools]
        try:
            resp = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": parts}],
                tools=fns,
                tool_choice="auto",
            )
        except self._openai.APIError as e:
            raise LLMError(f"API error: {e}") from e
        msg = resp.choices[0].message
        calls = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc.function.arguments}
            calls.append(ToolCall(id=tc.id, name=tc.function.name, args=args))
        usage = {"input_tokens": getattr(resp.usage, "prompt_tokens", 0), "output_tokens": getattr(resp.usage, "completion_tokens", 0)}
        return Decision(calls=calls[:1], text=(msg.content or "").strip(), usage=usage,
                        stop_reason=resp.choices[0].finish_reason or "")


# --------------------------------------------------------------------------- scripted (offline)


class ScriptedLLM:
    """A deterministic stand-in for the model, for offline runs and tests.

    Each scripted step names a tool and describes its target semantically (role/name/label/
    text/column/row). The script resolves that description against the *observation* to
    find a ref, exactly as a model reading the UI map would. It never touches the page.
    """

    def __init__(self, path: str | Path):
        doc = yaml.safe_load(Path(path).read_text())
        self.model = f"scripted:{Path(path).name}"
        self.steps: list[dict[str, Any]] = list(doc["steps"])
        self.i = 0

    async def decide(self, system: str, text: str, image_png: bytes | None, tools: list[dict[str, Any]],
                     observation: Observation | None = None) -> Decision:
        if self.i >= len(self.steps):
            return Decision(calls=[ToolCall("s-end", "finish", {"status": "impossible", "summary": "script exhausted"})])
        step = self.steps[self.i]
        self.i += 1
        args = dict(step.get("args", {}))
        if "match" in step:
            ref = _find_ref(observation, step["match"]) if observation else None
            if ref is None:
                return Decision(calls=[ToolCall(f"s-{self.i}", "request_human", {
                    "kind": "stuck", "reason": f"script could not find element matching {step['match']}"})])
            args["ref"] = ref
        return Decision(calls=[ToolCall(f"s-{self.i}", step["tool"], args)], text=step.get("say", ""))


def _norm(s: str | None) -> str:
    return " ".join((s or "").split()).lower()


def _find_ref(obs: Observation, m: dict[str, Any]) -> str | None:
    for f in obs.frames:
        if m.get("frame") and f.key != m["frame"]:
            continue
        if "follows" in m:  # the value cell right after a label cell, e.g. follows: "Name:"
            for i, n in enumerate(f.nodes[:-1]):
                if _norm(n.get("text")) == _norm(m["follows"]):
                    return f.nodes[i + 1]["ref"]
            continue
        for n in f.nodes:
            if "role" in m and n["role"] != m["role"]:
                continue
            if "name" in m and _norm(n.get("name")) != _norm(m["name"]):
                continue
            if "label" in m and _norm(n.get("label")) != _norm(m["label"]):
                continue
            if "text" in m and _norm(n.get("text")) != _norm(m["text"]):
                continue
            cell = n.get("cell") or {}
            if "column" in m and _norm(cell.get("header")) != _norm(m["column"]):
                continue
            if "row" in m and _norm(cell.get("rowKey")) != _norm(m["row"]):
                continue
            return n["ref"]
    return None


def make_llm(spec: str | None = None) -> LLM:
    """`anthropic`, `openai`, or `scripted:<path>`. Defaults to $UNDERSTUDY_LLM, else anthropic."""
    spec = spec or os.environ.get("UNDERSTUDY_LLM", "anthropic")
    if spec.startswith("scripted:"):
        return ScriptedLLM(spec.split(":", 1)[1])
    if spec == "openai":
        return OpenAICompatLLM()
    if spec == "anthropic":
        return AnthropicLLM()
    raise LLMError(f"unknown model provider {spec!r}")
