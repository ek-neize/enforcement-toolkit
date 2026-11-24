"""Command line:
python -m enforcement_toolkit.extraction.cli extract  --config config/extraction.yaml
python -m enforcement_toolkit.extraction.cli evaluate --pred data/processed/run/results.jsonl --gold data/gold/gold.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging

import yaml

from .evaluate import evaluate, load_jsonl, report
from .ingest import load_documents
from .llm_client import AnthropicClient, ResultCache
from .pipeline import PipelineConfig, run_batch


def cmd_extract(args) -> None:
    with open(args.config) as f:
        cfg = yaml.safe_load(f)
    docs = load_documents(cfg["input_dir"])
    if args.limit:
        docs = docs[: args.limit]
    client = AnthropicClient(model=cfg["model"], max_tokens=cfg.get("max_tokens", 4096))
    cache = ResultCache(cfg["cache_dir"]) if cfg.get("cache_dir") else None
    manifest = run_batch(docs, client, cfg["output_dir"], PipelineConfig(**cfg.get("pipeline", {})), cache)
    print(
        json.dumps(
            {k: manifest[k] for k in ("n_documents", "status_counts", "cache_hits", "tokens")}, indent=2
        )
    )


def cmd_evaluate(args) -> None:
    scores = evaluate(load_jsonl(args.pred), load_jsonl(args.gold))
    print(report(scores, csv_path=args.csv))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="extraction")
    sub = p.add_subparsers(required=True)

    e = sub.add_parser("extract", help="Run batch extraction")
    e.add_argument("--config", default="config/extraction.yaml")
    e.add_argument("--limit", type=int, help="Only process the first N documents (for dry runs)")
    e.set_defaults(func=cmd_extract)

    v = sub.add_parser("evaluate", help="Score predictions against gold labels")
    v.add_argument("--pred", required=True)
    v.add_argument("--gold", required=True)
    v.add_argument("--csv", help="Optional path to write the scores table")
    v.set_defaults(func=cmd_evaluate)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
