"""Thin, swappable LLM wrapper plus an on-disk result cache.

Anything with an `.extract(system, user, schema) -> LLMResult` method works,
which keeps the pipeline testable (see tests/) and provider-agnostic.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

TOOL_NAME = "record_case"


@dataclass
class LLMResult:
    data: dict
    input_tokens: int = 0
    output_tokens: int = 0


class LLMClient(Protocol):
    model: str

    def extract(self, system: str, user: str, schema: dict) -> LLMResult: ...


class AnthropicClient:
    """Structured output via forced tool use: the model must return JSON
    matching `schema`."""

    def __init__(self, model: str, max_tokens: int = 4096, temperature: float = 0.0, max_retries: int = 5):
        import anthropic  # imported lazily so tests don't need it

        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        # The SDK retries 429/5xx with exponential backoff.
        self._client = anthropic.Anthropic(max_retries=max_retries)

    def extract(self, system: str, user: str, schema: dict) -> LLMResult:
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=system,
            tools=[
                {
                    "name": TOOL_NAME,
                    "description": "Record the structured facts extracted from the case document.",
                    "input_schema": schema,
                }
            ],
            tool_choice={"type": "tool", "name": TOOL_NAME},
            messages=[{"role": "user", "content": user}],
        )
        for block in resp.content:
            if block.type == "tool_use" and block.name == TOOL_NAME:
                return LLMResult(block.input, resp.usage.input_tokens, resp.usage.output_tokens)
        raise RuntimeError(f"No tool call in response (stop_reason={resp.stop_reason})")


class ResultCache:
    """One JSON file per (model, prompt version, document hash).
    Re-runs are free, and identical inputs always give identical outputs."""

    def __init__(self, folder: str | Path):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(model: str, prompt_version: str, doc_sha256: str) -> str:
        return hashlib.sha256(f"{model}|{prompt_version}|{doc_sha256}".encode()).hexdigest()

    def get(self, key: str) -> dict | None:
        p = self.folder / f"{key}.json"
        return json.loads(p.read_text()) if p.exists() else None

    def set(self, key: str, value: dict) -> None:
        tmp = self.folder / f"{key}.json.tmp"
        tmp.write_text(json.dumps(value))
        tmp.replace(self.folder / f"{key}.json")  # atomic write
