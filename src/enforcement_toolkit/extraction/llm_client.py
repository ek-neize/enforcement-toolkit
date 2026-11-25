"""Thin, swappable LLM wrapper plus an on-disk result cache.

Anything with an `.extract(system, user, schema) -> LLMResult` method works,
which keeps the pipeline testable (see tests/) and provider-agnostic.

Claude API notes (API version 2026-10-21, anthropic SDK >= 2.x):
  * JSON is guaranteed with STRUCTURED OUTPUTS: output_config.format = json_schema.
    (Forcing a tool with tool_choice is rejected by Claude Sonnet 5.5.)
  * temperature / top_p / top_k are no longer accepted.
  * Thinking can run by default, so the response may contain `thinking` blocks before
    the answer: read blocks by type, and leave max_tokens room for thinking.
  Docs: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class LLMResult:
    data: dict
    input_tokens: int = 0
    output_tokens: int = 0


class LLMClient(Protocol):
    model: str

    def extract(self, system: str, user: str, schema: dict) -> LLMResult: ...


class AnthropicClient:
    def __init__(
        self,
        model: str,
        max_tokens: int = 16000,
        effort: str | None = "low",
        max_retries: int = 5,
        base_url: str | None = None,
    ):
        import anthropic  # imported lazily so tests that use a fake client don't need it

        self.model = model
        self.max_tokens = max_tokens  # covers thinking + answer
        self.effort = effort  # None = model default; extraction rarely needs deep reasoning
        # The SDK retries 429 / 5xx with exponential backoff.
        kwargs = {"max_retries": max_retries}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = anthropic.Anthropic(**kwargs)

    def extract(self, system: str, user: str, schema: dict) -> LLMResult:
        output_config: dict = {"format": {"type": "json_schema", "schema": schema}}
        if self.effort:
            output_config["effort"] = self.effort
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config=output_config,
        )
        if resp.stop_reason == "model_context_window_exceeded":
            raise RuntimeError("Document too long for the model's context window; lower pipeline.max_chars")
        if resp.stop_reason == "max_tokens":
            raise RuntimeError(f"Response cut off at max_tokens={self.max_tokens}; raise it in the config")
        if resp.stop_reason == "refusal":
            raise RuntimeError("Model declined to answer (stop_reason=refusal)")
        texts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        if not texts:
            raise RuntimeError(f"No text block in response (stop_reason={resp.stop_reason})")
        data = json.loads("".join(texts))
        return LLMResult(data, resp.usage.input_tokens, resp.usage.output_tokens)


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
        # unique temp name per write: two workers can finish identical documents at the same time
        tmp = self.folder / f"{key}.{uuid.uuid4().hex}.tmp"
        tmp.write_text(json.dumps(value))
        tmp.replace(self.folder / f"{key}.json")  # atomic: readers never see a half-written file
