"""Field-level precision / recall / F1 against a hand-labelled gold set.

gold.jsonl: one line per document -> {"doc_id": ..., "extraction": {...CaseExtraction...}}
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

_SUFFIXES = r"\b(inc|incorporated|ltd|limited|corp|corporation|llc|plc|co)\b"


def normalize(value) -> str:
    s = str(value).lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(_SUFFIXES, " ", s)
    return re.sub(r"\s+", " ", s).strip()


# field name -> function returning a set of normalized values
LIST_FIELDS = {
    "respondents": lambda e: {normalize(r["name"]) for r in e.get("respondents") or []},
    "securities": lambda e: {normalize(s) for s in e.get("securities") or []},
    "conduct_types": lambda e: set(e.get("conduct_types") or []),
    "legislation_cited": lambda e: {normalize(s) for s in e.get("legislation_cited") or []},
    "sanction_kinds": lambda e: {s["kind"] for s in e.get("sanctions") or []},
}
SCALAR_FIELDS = {
    "decision_date": lambda e: e.get("decision_date"),
    "conduct_start": lambda e: e.get("conduct_start"),
    "conduct_end": lambda e: e.get("conduct_end"),
    "profit_or_loss_avoided": lambda e: (e.get("profit_or_loss_avoided") or {}).get("amount"),
}
AMOUNT_TOLERANCE = 0.01  # 1% relative


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def _scalar_match(pred, gold) -> bool:
    if isinstance(pred, (int, float)) and isinstance(gold, (int, float)):
        return abs(pred - gold) <= AMOUNT_TOLERANCE * max(abs(gold), 1)
    return pred == gold


def evaluate(pred: dict[str, dict], gold: dict[str, dict]) -> dict[str, Counts]:
    """pred/gold: doc_id -> extraction dict. Missing predictions count as empty."""
    scores = {f: Counts() for f in [*LIST_FIELDS, *SCALAR_FIELDS]}
    for doc_id, g in gold.items():
        p = pred.get(doc_id) or {}
        for f, get in LIST_FIELDS.items():
            ps, gs = get(p), get(g)
            scores[f].tp += len(ps & gs)
            scores[f].fp += len(ps - gs)
            scores[f].fn += len(gs - ps)
        for f, get in SCALAR_FIELDS.items():
            pv, gv = get(p), get(g)
            if pv is not None and gv is not None and _scalar_match(pv, gv):
                scores[f].tp += 1
            else:
                scores[f].fp += pv is not None
                scores[f].fn += gv is not None
    return scores


def load_jsonl(path: str | Path) -> dict[str, dict]:
    out = {}
    with open(path) as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                out[r["doc_id"]] = r.get("extraction")
    return out


def report(scores: dict[str, Counts], csv_path: str | Path | None = None) -> str:
    rows = [(f, c.tp, c.fp, c.fn, c.precision, c.recall, c.f1) for f, c in scores.items()]
    lines = [f"{'field':<24}{'TP':>5}{'FP':>5}{'FN':>5}{'P':>7}{'R':>7}{'F1':>7}"]
    lines += [f"{f:<24}{tp:>5}{fp:>5}{fn:>5}{p:>7.2f}{r:>7.2f}{f1:>7.2f}" for f, tp, fp, fn, p, r, f1 in rows]
    if csv_path:
        with open(csv_path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["field", "tp", "fp", "fn", "precision", "recall", "f1"])
            w.writerows(rows)
    return "\n".join(lines)
