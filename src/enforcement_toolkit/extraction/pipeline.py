"""Batch extraction: documents -> LLM -> validate -> grounding check -> route.

Outputs (in out_dir):
  results.jsonl       one record per document (full audit trail)
  review_queue.jsonl  records a human must check before use
  manifest.json       run config, counts, token usage, timings
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from .ingest import Document
from .llm_client import LLMClient, ResultCache
from .prompts import PROMPT_VERSION, build_user_prompt, system_prompt
from .schema import CaseExtraction, output_schema

log = logging.getLogger(__name__)
SCHEMA = output_schema()


@dataclass
class PipelineConfig:
    prompt_version: str = PROMPT_VERSION
    run_name: str = ""
    workers: int = 4
    review_threshold: float = 0.7
    max_chars: int = 400_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _norm(s: str) -> str:
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


def find_ungrounded_evidence(ext: CaseExtraction, source_text: str) -> list[str]:
    """Return evidence quotes that do NOT appear verbatim in the source.
    This is the main hallucination guard: every fact must be traceable."""
    haystack = _norm(source_text)
    return [e.quote for e in ext.evidence if _norm(e.quote) not in haystack]


def process_document(
    doc: Document, client: LLMClient, cache: ResultCache | None, cfg: PipelineConfig
) -> dict:
    record = {
        "doc_id": doc.doc_id,
        "source_path": str(doc.path),
        "source_sha256": doc.sha256,
        "model": client.model,
        "prompt_version": cfg.prompt_version,
        "run_name": cfg.run_name,
        "processed_at": _now(),
        "from_cache": False,
        "status": None,
        "review_reasons": [],
        "usage": {"input_tokens": 0, "output_tokens": 0},
        "extraction": None,
    }
    reasons = record["review_reasons"]
    truncated = len(doc.text) > cfg.max_chars
    if truncated:
        reasons.append(f"truncated_to_{cfg.max_chars}_chars")

    key = ResultCache.key(client.model, cfg.prompt_version, doc.sha256)
    cached = cache.get(key) if cache else None
    if cached:
        raw = cached["data"]
        record["from_cache"] = True
        record["usage"] = cached.get("usage", record["usage"])  # keep the cost of producing it
    else:
        try:
            result = client.extract(
                system_prompt(cfg.prompt_version),
                build_user_prompt(doc.doc_id, doc.text[: cfg.max_chars]),
                SCHEMA,
            )
        except Exception as exc:  # keep the batch alive; record the failure
            log.exception("LLM call failed for %s", doc.doc_id)
            record["status"] = "failed"
            reasons.append(f"llm_error: {exc}")
            return record
        raw = result.data
        record["usage"] = {"input_tokens": result.input_tokens, "output_tokens": result.output_tokens}
        if cache:
            cache.set(key, {"data": raw, "usage": record["usage"], "created_at": _now()})

    try:
        ext = CaseExtraction.model_validate(raw)
    except ValidationError as exc:
        record["status"] = "failed"
        reasons.append(f"schema_validation: {exc.error_count()} errors")
        record["raw_output"] = raw
        return record

    ungrounded = find_ungrounded_evidence(ext, doc.text)
    if ungrounded:
        reasons.append(f"ungrounded_evidence: {len(ungrounded)} quote(s) not found in source")
        record["ungrounded_quotes"] = ungrounded
    if ext.confidence < cfg.review_threshold:
        reasons.append(f"low_confidence: {ext.confidence:.2f}")
    if not ext.respondents:
        reasons.append("no_respondents_found")
    if ext.conduct_start and ext.conduct_end and ext.conduct_start > ext.conduct_end:
        reasons.append("conduct_start_after_end")

    record["extraction"] = ext.model_dump(mode="json")
    record["status"] = "needs_review" if reasons else "ok"
    return record


def run_batch(
    docs: list[Document],
    client: LLMClient,
    out_dir: str | Path,
    cfg: PipelineConfig | None = None,
    cache: ResultCache | None = None,
) -> dict:
    cfg = cfg or PipelineConfig()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    started = _now()

    records = []
    with ThreadPoolExecutor(max_workers=cfg.workers) as pool:
        futures = {pool.submit(process_document, d, client, cache, cfg): d for d in docs}
        for i, fut in enumerate(as_completed(futures), 1):
            rec = fut.result()
            records.append(rec)
            log.info("[%d/%d] %s -> %s", i, len(docs), rec["doc_id"], rec["status"])
    records.sort(key=lambda r: r["doc_id"])  # deterministic output order

    with (out / "results.jsonl").open("w") as f_all, (out / "review_queue.jsonl").open("w") as f_rev:
        for r in records:
            line = json.dumps(r, ensure_ascii=False) + "\n"
            f_all.write(line)
            if r["status"] != "ok":
                f_rev.write(line)

    counts = {s: sum(r["status"] == s for r in records) for s in ("ok", "needs_review", "failed")}
    manifest = {
        "started_at": started,
        "finished_at": _now(),
        "model": client.model,
        "prompt_version": cfg.prompt_version,
        "run_name": cfg.run_name,
        "config": asdict(cfg),
        "n_documents": len(records),
        "status_counts": counts,
        "cache_hits": sum(r["from_cache"] for r in records),
        "tokens": {  # includes tokens of results served from cache (= cost to produce this run)
            "input": sum(r["usage"]["input_tokens"] for r in records),
            "output": sum(r["usage"]["output_tokens"] for r in records),
        },
        "source_hashes": {r["doc_id"]: r["source_sha256"] for r in records},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest
