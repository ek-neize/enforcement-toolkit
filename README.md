# Enforcement Analytics Toolkit

[![CI](https://github.com/YOUR_USERNAME/enforcement-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/YOUR_USERNAME/enforcement-toolkit/actions/workflows/ci.yml)

Python tools that support securities-enforcement work: data validation, detection of
suspicious trading, LLM-assisted document review and entity-relationship analysis.
Every output can be reproduced and traced back to a hashed source file.

> **Plain-language summary (LLM module):** Reviewing hundreds of tribunal decisions by
> hand is slow. This module reads each decision and fills in a standard form (who, what
> security, what conduct, what sanction). It saves the exact sentence behind each answer
> and sends anything doubtful to a human reviewer. Accuracy is measured against
> hand-checked examples rather than assumed.

## Repository layout

```
enforcement-toolkit/
├── config/
│   └── extraction.yaml            # model, paths, thresholds (no secrets)
├── data/
│   ├── sample/                    # synthetic demo data (fictional companies)
│   ├── custody_log.jsonl          # chain-of-custody log
│   ├── raw/                       # source docs, never modified (gitignored)
│   ├── gold/                      # hand-labelled evaluation set
│   └── processed/                 # pipeline outputs + LLM cache (gitignored)
├── src/enforcement_toolkit/
│   ├── extraction/                # ✅ Module 4: LLM document review
│   │   ├── schema.py              #   Pydantic output schema = contract with the LLM
│   │   ├── prompts.py             #   versioned prompts
│   │   ├── ingest.py              #   load docs + SHA-256 fingerprint
│   │   ├── llm_client.py          #   swappable client (forced tool use) + disk cache
│   │   ├── pipeline.py            #   batch run, validation, grounding check, routing
│   │   ├── evaluate.py            #   field-level precision / recall / F1
│   │   └── cli.py
│   ├── validation/                # ✅ Module 1: intake, chain of custody, data quality
│   │   ├── custody.py             #   append-only SHA-256 log + verify
│   │   ├── schemas.py             #   pandera rules → errors (rows quarantined)
│   │   ├── loader.py              #   parse, de-duplicate, split valid / quarantined
│   │   ├── checks.py              #   completeness & integrity checks → warnings
│   │   ├── report.py              #   run everything, write report + issues.json
│   │   ├── sample_data.py         #   fictional demo data with planted problems
│   │   └── cli.py
│   ├── detection/                 # 🔜 event study / insider-trading flags, spoofing
│   └── graph/                     # 🔜 entity-relationship network (networkx)
├── notebooks/                     # 🔜 training walkthrough for non-technical staff
├── reports/                       # 🔜 case memo, evaluation report
├── tests/
├── METHODOLOGY.md                 # assumptions, limitations, how to reproduce
└── pyproject.toml
```

## Module 1: Data intake and validation

> **Plain-language summary:** Before any analysis, every data file is fingerprinted, so it can
> later be proven unchanged. It is then checked for impossible values, duplicates, gaps and
> suspicious entries. Broken rows are set aside rather than silently fixed. Anything odd is
> listed in a report a case team can read.

```bash
python -m enforcement_toolkit.validation.cli sample --out data/sample      # demo data
python -m enforcement_toolkit.validation.cli validate --config config/validation.yaml
python -m enforcement_toolkit.validation.cli verify-custody                 # prove files unchanged
```
Outputs go to `reports/data_quality/`: `data_quality_report.md`, `issues.json` and one
`quarantine_<dataset>.csv` per dataset. Downstream modules call `run_validation(...).frames()` and
only ever see validated rows. Rules and limitations are in [METHODOLOGY.md](METHODOLOGY.md).

## Module 4: LLM document review: design choices (and why they matter for enforcement work)

| Choice | Why |
|---|---|
| **Forced tool use with a Pydantic schema** | The model must return valid JSON in a fixed shape, and the same model validates the output. |
| **Verbatim evidence quotes + grounding check** | Every fact must point to a sentence that appears word for word in the source. Invented quotes are caught automatically. |
| **Human review queue** | Low confidence, ungrounded quotes, missing respondents or inconsistent dates all send the record to a person. The LLM assists; it does not decide. |
| **SHA-256 of every source file + prompt version + model in each record** | Chain of custody. Any number can be traced back to its exact inputs. |
| **Disk cache keyed on (model, prompt, doc hash)** | Re-runs cost nothing and give identical outputs. |
| **Gold-set evaluation** | Accuracy is a measured number per field, not a claim. |
| **Document treated as data** | The prompt tells the model to ignore instructions inside documents (prompt-injection guard). |

## Quick start

```bash
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=...
pytest                                   # runs offline with a fake client

# put .txt / .pdf decisions in data/raw/decisions/, then:
python -m enforcement_toolkit.extraction.cli extract --limit 5     # dry run
python -m enforcement_toolkit.extraction.cli extract
python -m enforcement_toolkit.extraction.cli evaluate \
    --pred data/processed/extraction_run/results.jsonl \
    --gold data/gold/gold.jsonl --csv reports/eval_v1.csv
```

## Next steps
1. Collect about 300 public decisions, such as Capital Markets Tribunal decisions or SEC litigation releases.
2. Hand-label about 50 of them into `data/gold/gold.jsonl`, using the same schema.
3. Compare prompt versions (e.g. v1.0 vs. v1.1 with few-shot examples) and models. Report F1, cost and runtime for each.
4. For very long documents, add chunked map-reduce extraction instead of truncation.
5. For large runs, switch to the Message Batches API to cut cost.

## Continuous integration
Every push and pull request runs on GitHub Actions (`.github/workflows/ci.yml`): `ruff` lint and format checks,
then the test suite on Python 3.10–3.12, then a smoke run of the validator whose report is saved as a build artifact. The tests use a fake LLM client, so CI needs no API key and costs nothing.
