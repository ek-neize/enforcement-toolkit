import json
from pathlib import Path

from enforcement_toolkit.extraction.evaluate import evaluate
from enforcement_toolkit.extraction.ingest import load_documents
from enforcement_toolkit.extraction.llm_client import LLMResult, ResultCache
from enforcement_toolkit.extraction.pipeline import PipelineConfig, run_batch
from enforcement_toolkit.extraction.schema import tool_input_schema

DOC = """IN THE MATTER OF JANE DOE
Decision date: March 4, 2024.
Ms. Doe, a director of Acme Mining Inc., purchased shares of Acme Mining Inc.
before the public announcement of the takeover bid, contrary to s. 76(1) of the
Securities Act (Ontario). She made a profit of $125,000.
"""

GOOD = {
    "case_title": "In the Matter of Jane Doe",
    "decision_date": "2024-03-04",
    "respondents": [{"name": "Jane Doe", "entity_type": "individual", "role": "director"}],
    "securities": ["Acme Mining Inc."],
    "conduct_types": ["insider_trading"],
    "profit_or_loss_avoided": {"amount": 125000, "currency": "CAD"},
    "legislation_cited": ["Securities Act (Ontario) s. 76(1)"],
    "evidence": [
        {"field": "decision_date", "quote": "Decision date: March 4, 2024."},
        {"field": "legislation_cited", "quote": "contrary to s. 76(1) of the Securities Act (Ontario)"},
    ],
    "confidence": 0.92,
}


class FakeClient:
    model = "fake-model"

    def __init__(self, payload):
        self.payload, self.calls = payload, 0

    def extract(self, system, user, schema):
        self.calls += 1
        return LLMResult(self.payload, 1000, 200)


def _write_doc(tmp_path: Path) -> list:
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "doe_2024.txt").write_text(DOC)
    return load_documents(tmp_path / "raw")


def test_schema_has_no_refs():
    assert "$ref" not in json.dumps(tool_input_schema())


def test_good_extraction_is_ok_and_cached(tmp_path):
    docs = _write_doc(tmp_path)
    client, cache = FakeClient(GOOD), ResultCache(tmp_path / "cache")
    m1 = run_batch(docs, client, tmp_path / "out", PipelineConfig(workers=1), cache)
    m2 = run_batch(docs, client, tmp_path / "out", PipelineConfig(workers=1), cache)
    assert m1["status_counts"]["ok"] == 1
    assert client.calls == 1 and m2["cache_hits"] == 1


def test_hallucinated_quote_goes_to_review(tmp_path):
    docs = _write_doc(tmp_path)
    bad = {**GOOD, "evidence": [{"field": "x", "quote": "She confessed to everything."}]}
    run_batch(docs, FakeClient(bad), tmp_path / "out", PipelineConfig(workers=1))
    rec = json.loads((tmp_path / "out" / "review_queue.jsonl").read_text())
    assert rec["status"] == "needs_review"
    assert any(r.startswith("ungrounded_evidence") for r in rec["review_reasons"])


def test_invalid_output_fails_cleanly(tmp_path):
    docs = _write_doc(tmp_path)
    m = run_batch(docs, FakeClient({"confidence": 7}), tmp_path / "out", PipelineConfig(workers=1))
    assert m["status_counts"]["failed"] == 1


def test_evaluate_normalizes_names():
    pred = {
        "d1": {
            "respondents": [{"name": "Jane Doe"}],
            "securities": ["ACME MINING INC"],
            "decision_date": "2024-03-04",
        }
    }
    gold = {
        "d1": {
            "respondents": [{"name": "Jane Doe"}, {"name": "John Roe"}],
            "securities": ["Acme Mining Inc."],
            "decision_date": "2024-03-04",
        }
    }
    s = evaluate(pred, gold)
    assert s["securities"].f1 == 1.0
    assert s["respondents"].precision == 1.0 and s["respondents"].recall == 0.5
    assert s["decision_date"].tp == 1


def test_identical_documents_in_parallel_do_not_collide(tmp_path):
    """Regression: two workers caching the same document at once used to crash on the temp file."""
    (tmp_path / "raw").mkdir()
    for i in range(8):
        (tmp_path / "raw" / f"copy_{i}.txt").write_text(DOC)  # same content -> same cache key
    docs = load_documents(tmp_path / "raw")
    m = run_batch(
        docs, FakeClient(GOOD), tmp_path / "out", PipelineConfig(workers=8), ResultCache(tmp_path / "c")
    )
    assert m["status_counts"]["ok"] == 8
    assert not list((tmp_path / "c").glob("*.tmp"))
