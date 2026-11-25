"""Field-level precision / recall / F1 against a hand-labelled gold set, and a
comparison report across runs (model x prompt version).

Matching rules (documented in METHODOLOGY.md):
  * names, securities, statutes: normalised (case, punctuation, corporate suffixes,
    middle initials) then FUZZY matched, one-to-one, at similarity >= FUZZY_THRESHOLD,
    so "Exchange Act Section 10(b)" matches "Section 10(b) of the Exchange Act".
  * categories (conduct types, sanction kinds): exact.
  * dates: exact. Amounts: within 1%.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

_SUFFIXES = r"\b(inc|incorporated|ltd|limited|corp|corporation|llc|plc|co|lp|llp)\b"
_STOP = {"of", "the", "and", "a", "an", "act", "1934", "1933", "u", "s", "securities", "thereunder", "under"}
FUZZY_THRESHOLD = 0.8
CHAR_TYPO_THRESHOLD = 0.92  # character similarity only counts for near-identical strings (typos)
AMOUNT_TOLERANCE = 0.01  # 1% relative


def normalize(value, person: bool = False) -> str:
    s = str(value).lower()
    s = re.sub(r"(\d)\((\w{1,2})\)", r"\1\2", s)  # "10(b)" -> "10b", "17(a)" -> "17a"
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(_SUFFIXES, " ", s)
    if person:
        s = re.sub(r"\b[a-z]\b", " ", s)  # drop middle initials: "Jane Q. Doe" -> "jane doe"
    return re.sub(r"\s+", " ", s).strip()


def similarity(a: str, b: str) -> float:
    """Best of: word overlap (Jaccard), containment (all key words of the shorter
    reference appear in the longer one), and character similarity, which counts only
    for near-identical strings, so "John Smith" never matches "John Smithson"."""
    if a == b:
        return 1.0
    ta, tb = set(a.split()) - _STOP, set(b.split()) - _STOP
    jacc = len(ta & tb) / len(ta | tb) if ta | tb else 0.0
    small = min(len(ta), len(tb))
    contain = len(ta & tb) / small if small >= 2 else 0.0
    chars = SequenceMatcher(None, a, b).ratio()
    return max(jacc, contain, chars if chars >= CHAR_TYPO_THRESHOLD else 0.0)


def match_sets(pred: list[str], gold: list[str], fuzzy: bool) -> tuple[int, int, int]:
    """Greedy one-to-one matching. Returns (tp, fp, fn)."""
    p, g = list(dict.fromkeys(pred)), list(dict.fromkeys(gold))
    if not fuzzy:
        tp = len(set(p) & set(g))
        return tp, len(set(p)) - tp, len(set(g)) - tp
    pairs = sorted(((similarity(a, b), i, j) for i, a in enumerate(p) for j, b in enumerate(g)), reverse=True)
    used_p, used_g, tp = set(), set(), 0
    for sim, i, j in pairs:
        if sim < FUZZY_THRESHOLD:
            break
        if i not in used_p and j not in used_g:
            used_p.add(i)
            used_g.add(j)
            tp += 1
    return tp, len(p) - tp, len(g) - tp


# field -> (getter returning a list of strings, fuzzy?)
LIST_FIELDS = {
    "respondents": (lambda e: [normalize(r["name"], person=True) for r in e.get("respondents") or []], True),
    "securities": (lambda e: [normalize(s) for s in e.get("securities") or []], True),
    "conduct_types": (lambda e: list(e.get("conduct_types") or []), False),
    "legislation_cited": (lambda e: [normalize(s) for s in e.get("legislation_cited") or []], True),
    "sanction_kinds": (lambda e: [s["kind"] for s in e.get("sanctions") or []], False),
}
SCALAR_FIELDS = {
    "decision_date": lambda e: e.get("decision_date"),
    "conduct_start": lambda e: e.get("conduct_start"),
    "conduct_end": lambda e: e.get("conduct_end"),
    "profit_or_loss_avoided": lambda e: (e.get("profit_or_loss_avoided") or {}).get("amount"),
}


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
    def empty(self) -> bool:
        """Nothing in the answer key and nothing predicted: the field can't be scored."""
        return self.tp + self.fp + self.fn == 0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


def _scalar_match(pred, gold) -> bool:
    if isinstance(pred, (int, float)) and isinstance(gold, (int, float)):
        return abs(pred - gold) <= AMOUNT_TOLERANCE * max(abs(gold), 1)
    return pred == gold


def evaluate(pred: dict[str, dict], gold: dict[str, dict]) -> dict[str, Counts]:
    """pred/gold: doc_id -> extraction dict. Only gold documents are scored;
    a gold document with no prediction counts as an empty prediction."""
    scores = {f: Counts() for f in [*LIST_FIELDS, *SCALAR_FIELDS]}
    for doc_id, g in gold.items():
        p = pred.get(doc_id) or {}
        for f, (get, fuzzy) in LIST_FIELDS.items():
            tp, fp, fn = match_sets(get(p), get(g), fuzzy)
            scores[f].tp += tp
            scores[f].fp += fp
            scores[f].fn += fn
        for f, get in SCALAR_FIELDS.items():
            pv, gv = get(p), get(g)
            if pv is not None and gv is not None and _scalar_match(pv, gv):
                scores[f].tp += 1
            else:
                scores[f].fp += pv is not None
                scores[f].fn += gv is not None
    return scores


def macro_f1(scores: dict[str, Counts]) -> float:
    """Average F1 over fields that have something to score (empty fields are excluded, not 0)."""
    scored = [c.f1 for c in scores.values() if not c.empty]
    return sum(scored) / len(scored) if scored else 0.0


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
    lines.append(f"{'MACRO F1':<24}{'':>15}{'':>14}{macro_f1(scores):>7.2f}")
    if csv_path:
        with open(csv_path, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["field", "tp", "fp", "fn", "precision", "recall", "f1"])
            w.writerows(rows)
    return "\n".join(lines)


# ---------------------------------------------------------------- comparison across runs
def run_summary(run_dir: Path, gold: dict[str, dict], pricing: dict[str, dict]) -> dict:
    """Score one run (a folder written by run_batch) against gold, plus cost and review stats."""
    manifest = json.loads((run_dir / "manifest.json").read_text())
    records = [json.loads(x) for x in (run_dir / "results.jsonl").read_text().splitlines() if x.strip()]
    pred = {r["doc_id"]: r.get("extraction") for r in records}
    scores = evaluate(pred, gold)
    n = len(records)
    price = pricing.get(manifest["model"], {})
    tin, tout = manifest["tokens"]["input"], manifest["tokens"]["output"]
    cost = (tin * price.get("input", 0) + tout * price.get("output", 0)) / 1e6 if price else None
    ungrounded = sum(any(x.startswith("ungrounded") for x in r["review_reasons"]) for r in records)
    return {
        "run": manifest.get("run_name") or run_dir.name,
        "model": manifest["model"],
        "prompt": manifest["prompt_version"],
        "docs": n,
        "gold_docs_scored": len(gold),
        "macro_f1": macro_f1(scores),
        "scores": scores,
        "needs_review_pct": 100 * sum(r["status"] != "ok" for r in records) / n if n else 0,
        "ungrounded_pct": 100 * ungrounded / n if n else 0,
        "failed": sum(r["status"] == "failed" for r in records),
        "tokens_in": tin,
        "tokens_out": tout,
        "cost_usd": cost,
        "cost_per_100_docs": cost / n * 100 if cost is not None and n else None,
    }


def comparison_markdown(summaries: list[dict], pricing_note: str = "") -> str:
    if not summaries:
        return "# Extraction comparison\n\n_No runs found._\n"
    fields = list(summaries[0]["scores"])
    md = [
        "# Extraction comparison\n",
        f"Scored against **{summaries[0]['gold_docs_scored']} hand-labelled documents**. "
        "F1 = balance of precision (how much of what the model extracted is right) and recall "
        "(how much of what is there the model found). 1.00 is perfect.\n",
        "## Summary\n",
        "| run | model | prompt | macro F1 | needs review | ungrounded quotes | failed | cost / 100 docs |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in summaries:
        cost = f"${s['cost_per_100_docs']:.2f}" if s["cost_per_100_docs"] is not None else "n/a"
        md.append(
            f"| {s['run']} | {s['model']} | {s['prompt']} | **{s['macro_f1']:.2f}** | {s['needs_review_pct']:.0f}% "
            f"| {s['ungrounded_pct']:.0f}% | {s['failed']} | {cost} |"
        )
    md += ["\n## F1 by field\n", "| field | " + " | ".join(s["run"] for s in summaries) + " |",
           "|---|" + "---|" * len(summaries)]  # fmt: skip
    for f in fields:
        cells = ["n/a" if s["scores"][f].empty else f"{s['scores'][f].f1:.2f}" for s in summaries]
        md.append(f"| {f} | " + " | ".join(cells) + " |")
    md += [
        "\n## Notes\n",
        "- Names, securities and statutes are matched fuzzily after normalisation; categories and dates exactly; "
        "amounts within 1%. See `METHODOLOGY.md`.\n",
        "- *n/a* = nothing to find in the labelled documents and nothing predicted; left out of the macro F1.\n",
        "- *Needs review* = sent to a human by the pipeline's own checks (low confidence, a quote not found in the "
        "source, missing respondents, inconsistent dates).\n",
        f"- Cost = tokens × list price per model. {pricing_note}\n",
    ]
    return "\n".join(md)
