import json

import yaml

from enforcement_toolkit.extraction.evaluate import evaluate, match_sets, normalize, run_summary
from enforcement_toolkit.extraction.ingest import load_documents
from enforcement_toolkit.extraction.labeling import load_gold, prepare, status
from enforcement_toolkit.extraction.llm_client import LLMResult
from enforcement_toolkit.extraction.pipeline import PipelineConfig, run_batch
from enforcement_toolkit.extraction.prompts import PROMPTS, system_prompt
from enforcement_toolkit.extraction.sec_releases import parse_release

PAGE = """<html><head><script>var x=1;</script><style>p{}</style></head><body>
<header><nav>Skip to main content | Newsroom | Enforcement</nav></header>
<main>
<h2>Litigation Release No. 26692 / November 20, 2026</h2>
<h3>Securities and Exchange Commission v. Jane Q. Doe, No. 1:26-cv-0001</h3>
<p>On November 20, 2026, the Securities and Exchange Commission charged Jane Q. Doe with insider
trading ahead of the acquisition of Acme Mining Inc.</p>
<p>According to the complaint, Doe bought shares after learning material nonpublic information.</p>
<h3>Resources</h3><ul><li>SEC Complaint</li></ul>
</main>
<footer>Return to top | Contact | Privacy</footer></body></html>"""


def test_parse_release_keeps_body_only():
    r = parse_release(PAGE)
    assert r.number == "26692" and r.date == "November 20, 2026" and r.complete
    assert r.title.startswith("Securities and Exchange Commission v. Jane Q. Doe")
    assert "material nonpublic information" in r.body
    for junk in ("Skip to main", "var x", "SEC Complaint", "Privacy"):
        assert junk not in r.body


def test_unrecognised_layout_is_flagged_not_silently_cut():
    r = parse_release("<html><body><p>Some other page</p></body></html>")
    assert not r.complete and "Some other page" in r.body


def test_fuzzy_matching_of_names_and_statutes():
    assert normalize("Jane Q. Doe", person=True) == normalize("Jane Doe", person=True)
    tp, fp, fn = match_sets(
        [normalize("Exchange Act Section 10(b)"), normalize("Rule 10b-5")],
        [
            normalize("Section 10(b) of the Securities Exchange Act of 1934"),
            normalize("Rule 10b-5 thereunder"),
        ],
        fuzzy=True,
    )
    assert (tp, fp, fn) == (2, 0, 0)
    assert match_sets([normalize("Acme Mining")], [normalize("Boreal Resources")], fuzzy=True) == (0, 1, 1)
    # different provisions must NOT match
    assert match_sets([normalize("Section 17(a) of the Securities Act")],
                      [normalize("Section 10(b) of the Exchange Act")], fuzzy=True) == (0, 1, 1)  # fmt: skip
    assert match_sets([normalize("Rule 10b-5")], [normalize("Rule 14e-3")], fuzzy=True) == (0, 1, 1)
    assert match_sets([normalize("John Smith", person=True)], [normalize("John Smithson", person=True)],
                      fuzzy=True) == (0, 1, 1)  # fmt: skip


def test_prompt_versions_are_distinct_and_v11_adds_definitions():
    assert set(PROMPTS) >= {"v1.0", "v1.1"}
    assert system_prompt("v1.1").startswith(system_prompt("v1.0"))
    assert "relief defendant" in system_prompt("v1.1") and "relief defendant" not in system_prompt("v1.0")


GOOD = {
    "case_title": "SEC v. Jane Q. Doe",
    "decision_date": "2026-11-20",
    "respondents": [{"name": "Jane Q. Doe", "entity_type": "individual", "role": None}],
    "securities": ["Acme Mining Inc."],
    "conduct_types": ["insider_trading"],
    "legislation_cited": [],
    "sanctions": [],
    "evidence": [{"field": "decision_date", "quote": "On November 20, 2026"}],
    "confidence": 0.9,
}


class Fake:
    model = "claude-sonnet-5-5"

    def extract(self, system, user, schema):
        return LLMResult(GOOD, 3000, 800)


def test_end_to_end_extract_label_compare(tmp_path):
    docs_dir = tmp_path / "text"
    docs_dir.mkdir()
    (docs_dir / "lr-26692.txt").write_text(parse_release(PAGE).body)
    docs = load_documents(docs_dir)
    run = tmp_path / "runs" / "sonnet-v1.1"
    run_batch(docs, Fake(), run, PipelineConfig(prompt_version="v1.1", run_name="sonnet-v1.1", workers=1))

    labels = tmp_path / "labels"
    written = prepare(docs_dir, labels, n=5, blank=0, prefill_results=run / "results.jsonl")
    assert len(written) == 1 and status(labels)["reviewed"] == 0
    label = json.loads(written[0].read_text())
    assert label["_start"] == "prefilled from model run" and "evidence" not in label["extraction"]

    # reviewer corrects one field and marks it reviewed
    label["extraction"]["legislation_cited"] = ["Section 10(b) of the Exchange Act"]
    label["_reviewed"] = True
    written[0].write_text(json.dumps(label))
    gold, problems = load_gold(labels)
    assert not problems and list(gold) == ["lr-26692"]

    s = run_summary(run, gold, {"claude-sonnet-5-5": {"input": 2.0, "output": 10.0}})
    assert s["scores"]["respondents"].f1 == 1.0
    assert s["scores"]["legislation_cited"].recall == 0.0  # the model missed it
    assert abs(s["cost_usd"] - (3000 * 2 + 800 * 10) / 1e6) < 1e-9
    assert prepare(docs_dir, labels, n=5) == []  # never overwrites reviewed work


def test_bad_label_is_reported_not_used(tmp_path):
    (tmp_path / "x.json").write_text(json.dumps(
        {"doc_id": "x", "_reviewed": True, "extraction": {**GOOD, "conduct_types": ["insider_traiding"]}}
    ))  # fmt: skip
    gold, problems = load_gold(tmp_path)
    assert gold == {} and "x.json" in problems[0]


def test_config_runs_are_valid():
    cfg = yaml.safe_load(open("config/extraction.yaml"))
    for r in cfg["runs"]:
        assert r["prompt_version"] in PROMPTS
        assert r["model"] in cfg["pricing_usd_per_mtok"]


def test_missing_prediction_counts_as_missed():
    s = evaluate({}, {"d": {"respondents": [{"name": "A"}], "decision_date": "2026-01-01"}})
    assert s["respondents"].fn == 1 and s["decision_date"].fn == 1


def test_empty_fields_are_not_scored_as_zero():
    from enforcement_toolkit.extraction.evaluate import macro_f1

    gold = {"d": {"respondents": [{"name": "A"}]}}
    s = evaluate({"d": {"respondents": [{"name": "A"}]}}, gold)
    assert s["respondents"].f1 == 1.0 and s["sanction_kinds"].empty
    assert macro_f1(s) == 1.0  # only respondents had anything to score
