"""Gold labels: one JSON file per document in data/gold/labels/, edited by hand.

Workflow (see docs/labeling_guide.md):
  1. `label-prepare` picks a reproducible random sample of documents and writes a label
     file for each. The first `--blank` files start EMPTY (labelled from scratch, to measure
     the anchoring bias of pre-filled labels). The rest start pre-filled from a model run,
     which is faster, but you must check every field against the document.
  2. Open the .txt and the .json side by side, fix the JSON, set "_reviewed": true.
  3. Only reviewed files count. Each one is validated against the schema on load, so
     a typo (e.g. a conduct type that doesn't exist) is caught immediately.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .schema import CaseExtraction

BLANK = {
    "case_title": None,
    "decision_date": None,
    "respondents": [],
    "securities": [],
    "conduct_types": [],
    "conduct_start": None,
    "conduct_end": None,
    "profit_or_loss_avoided": None,
    "sanctions": [],
    "legislation_cited": [],
}
_MODEL_ONLY = ("evidence", "confidence", "notes")  # not labelled by hand


def _sample(doc_ids: list[str], n: int, seed: str) -> list[str]:
    """Reproducible pseudo-random sample: sort by hash(seed + id)."""
    return sorted(doc_ids, key=lambda d: hashlib.sha256(f"{seed}{d}".encode()).hexdigest())[:n]


def prepare(docs_dir: str | Path, labels_dir: str | Path, n: int = 50, blank: int = 15,
            prefill_results: str | Path | None = None, seed: str = "gold-v1") -> list[Path]:  # fmt: skip
    docs = sorted(p.stem for p in Path(docs_dir).glob("*.txt"))
    chosen = _sample(docs, n, seed)
    prefill = {}
    if prefill_results and Path(prefill_results).exists():
        for line in Path(prefill_results).read_text().splitlines():
            r = json.loads(line)
            if r.get("extraction"):
                prefill[r["doc_id"]] = {k: v for k, v in r["extraction"].items() if k not in _MODEL_ONLY}
    out = Path(labels_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for i, doc_id in enumerate(chosen):
        path = out / f"{doc_id}.json"
        if path.exists():
            continue  # never overwrite work already done
        use_prefill = i >= blank and doc_id in prefill
        label = {
            "doc_id": doc_id,
            "source_text": str(Path(docs_dir) / f"{doc_id}.txt"),
            "_reviewed": False,
            "_start": "prefilled from model run" if use_prefill else "blank",
            "_notes": "",
            "extraction": prefill[doc_id] if use_prefill else dict(BLANK),
        }
        path.write_text(json.dumps(label, indent=2, ensure_ascii=False) + "\n")
        written.append(path)
    return written


def load_gold(labels_dir: str | Path) -> tuple[dict[str, dict], list[str]]:
    """Reviewed labels only. Returns (doc_id -> extraction, list of problems found)."""
    gold, problems = {}, []
    for path in sorted(Path(labels_dir).glob("*.json")):
        try:
            label = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            problems.append(f"{path.name}: not valid JSON ({e})")
            continue
        if not label.get("_reviewed"):
            continue
        ext = {**label["extraction"], "confidence": 1.0}
        try:
            CaseExtraction.model_validate(ext)
        except Exception as e:  # noqa: BLE001
            problems.append(f"{path.name}: {str(e).splitlines()[0]}")
            continue
        gold[label["doc_id"]] = label["extraction"]
    return gold, problems


def status(labels_dir: str | Path) -> dict:
    files = list(Path(labels_dir).glob("*.json"))
    labels = [json.loads(p.read_text()) for p in files]
    return {
        "files": len(files),
        "reviewed": sum(bool(x.get("_reviewed")) for x in labels),
        "reviewed_blank_start": sum(bool(x.get("_reviewed")) and x.get("_start") == "blank" for x in labels),
    }
