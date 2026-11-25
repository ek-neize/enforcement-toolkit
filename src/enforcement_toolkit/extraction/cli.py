"""Module 4 command line.

python -m enforcement_toolkit.extraction.cli fetch-sec --user-agent "Your Name you@example.com" --start 26694 --want 120
python -m enforcement_toolkit.extraction.cli extract --run sonnet-v1.0 --limit 3      # dry run first!
python -m enforcement_toolkit.extraction.cli extract --all
python -m enforcement_toolkit.extraction.cli label-prepare --from-run sonnet-v1.0
python -m enforcement_toolkit.extraction.cli label-status
python -m enforcement_toolkit.extraction.cli compare
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import yaml

from .evaluate import comparison_markdown, evaluate, load_jsonl, report, run_summary
from .ingest import load_documents
from .labeling import load_gold, prepare, status
from .llm_client import AnthropicClient, ResultCache
from .pipeline import PipelineConfig, run_batch


def _cfg(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _run_dir(cfg: dict, name: str) -> Path:
    return Path(cfg["output_root"]) / name


def cmd_fetch_sec(args) -> None:
    from .sec_releases import fetch

    path = fetch(args.out, args.user_agent, start=args.start, want=args.want, max_requests=args.max_requests,
                 delay=args.delay)  # fmt: skip
    print(f"Manifest: {path}")


def cmd_reparse_sec(args) -> None:
    from .sec_releases import reparse

    r = reparse(args.out)
    print(f"{r['releases']} releases, {r['text_files_changed']} text file(s) updated")
    print(f"Layout not recognised: {', '.join(r['not_recognised']) or 'none'}")


def cmd_extract(args) -> None:
    cfg = _cfg(args.config)
    runs = cfg["runs"] if args.all else [r for r in cfg["runs"] if r["name"] == args.run]
    if not runs:
        sys.exit(f"No run named {args.run!r}. Runs in config: {', '.join(r['name'] for r in cfg['runs'])}")
    docs = load_documents(cfg["input_dir"])
    if args.only_gold:
        gold, _ = load_gold(cfg["gold_dir"])
        docs = [d for d in docs if d.doc_id in gold]
    if args.limit:
        docs = docs[: args.limit]
    if not docs:
        sys.exit(f"No documents found in {cfg['input_dir']} (run fetch-sec first)")
    cache = ResultCache(cfg["cache_dir"])
    for r in runs:
        client = AnthropicClient(
            model=r["model"], max_tokens=cfg.get("max_tokens", 16000), effort=r.get("effort")
        )
        pcfg = PipelineConfig(
            prompt_version=r["prompt_version"], run_name=r["name"], **cfg.get("pipeline", {})
        )
        print(f"\n=== {r['name']}: {r['model']} / prompt {r['prompt_version']} on {len(docs)} documents ===")
        m = run_batch(docs, client, _run_dir(cfg, r["name"]), pcfg, cache)
        print(json.dumps({k: m[k] for k in ("status_counts", "cache_hits", "tokens")}, indent=2))


def cmd_label_prepare(args) -> None:
    cfg = _cfg(args.config)
    prefill = _run_dir(cfg, args.from_run) / "results.jsonl" if args.from_run else None
    written = prepare(cfg["input_dir"], cfg["gold_dir"], n=args.n, blank=args.blank, prefill_results=prefill)
    print(f"Wrote {len(written)} new label file(s) to {cfg['gold_dir']}. Guide: docs/labeling_guide.md")


def cmd_label_status(args) -> None:
    cfg = _cfg(args.config)
    s = status(cfg["gold_dir"])
    _, problems = load_gold(cfg["gold_dir"])
    print(
        f"{s['reviewed']}/{s['files']} label files reviewed ({s['reviewed_blank_start']} labelled from blank)"
    )
    for p in problems:
        print(f"  PROBLEM {p}")


def cmd_compare(args) -> None:
    cfg = _cfg(args.config)
    gold, problems = load_gold(cfg["gold_dir"])
    for p in problems:
        print(f"PROBLEM (label skipped) {p}")
    if not gold:
        sys.exit("No reviewed gold labels yet: run label-prepare, review some files, then compare.")
    summaries = []
    for r in cfg["runs"]:
        d = _run_dir(cfg, r["name"])
        if (d / "manifest.json").exists():
            summaries.append(run_summary(d, gold, cfg.get("pricing_usd_per_mtok", {})))
    out = Path(cfg["report_dir"])
    out.mkdir(parents=True, exist_ok=True)
    (out / "comparison.md").write_text(comparison_markdown(summaries, cfg.get("pricing_note", "")))
    for s in summaries:
        print(f"{s['run']:<16} macro F1 {s['macro_f1']:.2f}   review {s['needs_review_pct']:.0f}%   "
              + (f"${s['cost_per_100_docs']:.2f} / 100 docs" if s["cost_per_100_docs"] is not None else ""))  # fmt: skip
    print(f"\nReport: {out / 'comparison.md'}")


def cmd_evaluate(args) -> None:
    print(report(evaluate(load_jsonl(args.pred), load_jsonl(args.gold)), csv_path=args.csv))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="extraction")
    p.add_argument("--config", default="config/extraction.yaml")
    sub = p.add_subparsers(required=True)

    f = sub.add_parser("fetch-sec", help="Download SEC litigation releases (run on your own machine)")
    f.add_argument(
        "--user-agent", required=True, help='Your name and email, e.g. "Jane Doe jane@example.com"'
    )
    f.add_argument(
        "--start", type=int, required=True, help="Latest release number to start from (e.g. 26694)"
    )
    f.add_argument("--want", type=int, default=120, help="How many matching releases to keep")
    f.add_argument("--max-requests", type=int, default=1500)
    f.add_argument("--delay", type=float, default=1.0, help="Seconds between requests")
    f.add_argument("--out", default="data/raw/sec_releases")
    f.set_defaults(func=cmd_fetch_sec)

    rp = sub.add_parser("reparse-sec", help="Rebuild the text files from the saved pages (no download)")
    rp.add_argument("--out", default="data/raw/sec_releases")
    rp.set_defaults(func=cmd_reparse_sec)

    e = sub.add_parser("extract", help="Run the LLM extraction")
    g = e.add_mutually_exclusive_group(required=True)
    g.add_argument("--run", help="Name of one run from the config")
    g.add_argument("--all", action="store_true", help="Every run in the config")
    e.add_argument("--limit", type=int, help="Only the first N documents (dry run)")
    e.add_argument("--only-gold", action="store_true", help="Only documents with reviewed gold labels")
    e.set_defaults(func=cmd_extract)

    lp = sub.add_parser("label-prepare", help="Create label files for a reproducible sample")
    lp.add_argument("--n", type=int, default=50)
    lp.add_argument("--blank", type=int, default=15, help="How many start empty (labelled from scratch)")
    lp.add_argument("--from-run", help="Pre-fill the rest from this run's output")
    lp.set_defaults(func=cmd_label_prepare)

    ls = sub.add_parser("label-status", help="How many labels are reviewed, and any errors in them")
    ls.set_defaults(func=cmd_label_status)

    c = sub.add_parser("compare", help="Score every run against the gold labels; write the comparison report")
    c.set_defaults(func=cmd_compare)

    v = sub.add_parser("evaluate", help="Score one predictions file against one gold file")
    v.add_argument("--pred", required=True)
    v.add_argument("--gold", required=True)
    v.add_argument("--csv")
    v.set_defaults(func=cmd_evaluate)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
