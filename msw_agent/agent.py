"""The agent loop: sends the conversation to Claude, runs the tools Claude asks
for, and repeats until Claude has a final answer."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import anthropic

from .prompts import PROMPTS
from .tools import (
    GET_CITATION,
    LIST_SOURCES,
    SAVE_SOURCE,
    SEARCH_LITERATURE,
    WEB_FETCH,
    WEB_SEARCH,
    Library,
    ToolBox,
)

DEFAULT_MODEL = "claude-opus-5"
# Models that accept server-side refusal fallbacks in "default" mode.
FALLBACK_MODELS = {"claude-opus-5", "claude-fable-5-1"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_STEPS = 25  # model calls per user message, a guard against runaway loops

MODE_TOOLS = {
    "research": [SEARCH_LITERATURE, GET_CITATION, SAVE_SOURCE, LIST_SOURCES, WEB_SEARCH, WEB_FETCH],
    "feedback": [GET_CITATION, SEARCH_LITERATURE, LIST_SOURCES],
    "checklist": [],
}

# Callback receives (event_kind, detail). Kinds: "tool", "notice".
EventCallback = Callable[[str, str], None]


def default_data_dir() -> Path:
    return Path(os.environ.get("MSW_AGENT_DATA_DIR", Path.cwd() / "data"))


@dataclass
class Reply:
    text: str
    stop_reason: str | None
    notices: list[str] = field(default_factory=list)


def _describe_call(name: str, tool_input: dict) -> str:
    if name in ("web_search", "search_literature"):
        return f"{name}: {tool_input.get('query', '')}"
    if name == "web_fetch":
        return f"web_fetch: {tool_input.get('url', '')}"
    if name in ("get_citation", "save_source"):
        return f"{name}: {tool_input.get('doi', '')}"
    return name


class Agent:
    def __init__(
        self,
        mode: str = "research",
        client: Any | None = None,
        library: Library | None = None,
        model: str | None = None,
        effort: str | None = None,
    ):
        if mode not in PROMPTS:
            raise ValueError(f"mode must be one of {sorted(PROMPTS)}")
        self.mode = mode
        self.client = client or anthropic.Anthropic()
        self.library = library or Library(default_data_dir() / "library.json")
        self.toolbox = ToolBox(self.library)
        self.model = model or os.environ.get("MSW_AGENT_MODEL", DEFAULT_MODEL)
        self.effort = effort or os.environ.get("MSW_AGENT_EFFORT", "high")
        self.messages: list[dict] = []
        self.usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}

    def _request_kwargs(self) -> dict:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 16000,
            "system": PROMPTS[self.mode],
            "messages": self.messages,
            "cache_control": {"type": "ephemeral"},
        }
        if MODE_TOOLS[self.mode]:
            kwargs["tools"] = MODE_TOOLS[self.mode]
        if not self.model.startswith("claude-haiku"):
            kwargs["output_config"] = {"effort": self.effort}
        if self.model in FALLBACK_MODELS:
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        return kwargs

    def _track_usage(self, usage: Any) -> None:
        for key in self.usage:
            self.usage[key] += getattr(usage, key, 0) or 0

    def send(self, content: str | list, on_event: EventCallback | None = None) -> Reply:
        """Send one user message and run the agent until it produces an answer."""
        emit = on_event or (lambda kind, detail: None)
        self.messages.append({"role": "user", "content": content})
        notices: list[str] = []
        response = None

        for _ in range(MAX_STEPS):
            response = self.client.beta.messages.create(**self._request_kwargs())
            self._track_usage(response.usage)
            blocks = list(response.content)

            for b in blocks:
                if b.type in ("server_tool_use", "tool_use"):
                    emit("tool", _describe_call(b.name, dict(b.input or {})))

            if response.stop_reason != "tool_use":
                # A tool call cut off by max_tokens can't be answered; drop it so the
                # history stays valid for the next turn.
                blocks = [b for b in blocks if b.type != "tool_use"]
            if blocks:
                self.messages.append({"role": "assistant", "content": blocks})

            if response.stop_reason == "tool_use":
                results = []
                for b in blocks:
                    if b.type != "tool_use":
                        continue
                    text, is_error = self.toolbox.run(b.name, dict(b.input or {}))
                    if is_error:
                        emit("notice", f"{b.name} failed: {text}")
                    results.append(
                        {"type": "tool_result", "tool_use_id": b.id, "content": text, "is_error": is_error}
                    )
                self.messages.append({"role": "user", "content": results})
                continue
            if response.stop_reason == "pause_turn":
                # Server-side tools (web search) hit their per-request limit; re-sending
                # the conversation lets the server resume where it left off.
                continue
            break
        else:
            notices.append("Stopped after too many steps. Try asking a narrower question.")

        if response is not None and response.stop_reason == "refusal":
            notices.append("Claude declined this request. Try rephrasing it.")
        if response is not None and response.stop_reason == "max_tokens":
            notices.append("The answer hit the length limit and was cut off. Ask it to continue.")

        text = "\n\n".join(
            b.text for b in (response.content if response else []) if b.type == "text" and b.text
        ).strip()
        for n in notices:
            emit("notice", n)
        return Reply(text=text, stop_reason=response.stop_reason if response else None, notices=notices)

    def reset(self) -> None:
        self.messages = []
