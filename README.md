# Enforcement Analytics Toolkit

[![CI](https://github.com/ek-neize/enforcement-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/ek-neize/enforcement-toolkit/actions/workflows/ci.yml)

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
│   │   ├── sec_releases.py        #   polite downloader for SEC litigation releases + custody log
│   │   ├── schema.py              #   Pydantic output schema = contract with the LLM
│   │   ├── prompts.py             #   versioned prompts (v1.0, v1.1)
│   │   ├── ingest.py              #   load docs + SHA-256 fingerprint
│   │   ├── llm_client.py          #   Claude client (structured outputs) + disk cache
│   │   ├── pipeline.py            #   batch run, validation, grounding check, routing
│   │   ├── labeling.py            #   gold-label files: sample, pre-fill, validate
│   │   ├── evaluate.py            #   field-level F1 (fuzzy matching), run comparison, cost
│   │   └── cli.py
│   ├── validation/                # ✅ Module 1: intake, chain of custody, data quality
│   │   ├── custody.py             #   append-only SHA-256 log + verify
│   │   ├── schemas.py             #   pandera rules → errors (rows quarantined)
│   │   ├── loader.py              #   parse, de-duplicate, split valid / quarantined
│   │   ├── checks.py              #   completeness & integrity checks → warnings
│   │   ├── report.py              #   run everything, write report + issues.json
│   │   ├── sample_data.py         #   fictional demo data with planted problems
│   │   └── cli.py
│   ├── detection/                 # ✅ Module 2: insider-trading screen
│   │   ├── event_study.py         #   market model, abnormal returns, CAR, t-stats, abnormal volume
│   │   ├── screening.py           #   match trades to news, flag, score with reasons
│   │   ├── charts.py              #   one chart per event with insider trades marked
│   │   ├── report.py              #   case-team report + CSVs
│   │   └── cli.py
│   └── graph/                     # ✅ Module 3: relationship network
│       ├── build.py               #   people, entities, accounts, companies + sourced links
│       ├── analysis.py            #   account trades before news, shortest path to an insider
│       ├── charts.py              #   network diagram per event (deterministic layout)
│       ├── report.py              #   report + GraphML for Gephi
│       └── cli.py
├── docs/labeling_guide.md         # rules for the hand-labelled answer key
├── notebooks/                     # 🔜 training walkthrough for non-technical staff
├── reports/                       # generated reports; case_memo/ = the write-up for a case team
├── tests/
├── METHODOLOGY.md                 # assumptions, limitations, how to reproduce
└── pyproject.toml
```

## 📄 Case memo: what this looks like for a case team

**[ACME case memo (PDF)](reports/case_memo/ACME_case_memo.pdf)** · [Markdown version](reports/case_memo/ACME_case_memo.md)

A two-page memo, with exhibits, of the kind a data science team would send to investigators. It combines
Modules 1–3: what happened before the ACME takeover, who traded, how they connect, what the analysis does
**not** show, and the recommended next steps. All names and figures are fictional (synthetic data).
Rebuild the PDF with `reports/case_memo/build_pdf.sh`.

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

## Module 2: Insider-trading screen

> **Plain-language summary:** For each piece of company news, the tool measures how much the
> stock moved *beyond what the overall market did*, and whether that move was too big to be
> chance. It then finds insiders who traded shortly before that news, in the direction that
> would profit, and ranks them. Every point in a trade's score comes with a written reason. The
> output is a list of leads for investigators, not accusations.

```bash
python -m enforcement_toolkit.detection.cli --config config/detection.yaml
```
This runs Module 1 first, so detection only ever uses validated rows. Outputs go to
`reports/detection/`: `detection_report.md` (ranked trades, a short narrative for each, and
charts), `event_study.csv` and `screened_trades.csv`.

On the sample data it flags the CFO and a director buying ACME before its takeover
(High priority) and a VP selling CNDR before a guidance cut (Medium). Ordinary trades with no
news nearby are not flagged.

## Module 3: Relationship network

> **Plain-language summary:** Insiders don't always trade in their own names. This module adds
> brokerage account records and known relationships (family, trusts, shared board seats), each
> with the source it came from. It then traces whether accounts that traded profitably before
> the news connect back to an insider who knew. It shows the chain step by step, for example
> *account → Kevin Whitfield → spouse of → Dana Whitfield → CFO of ACME*.

```bash
python -m enforcement_toolkit.graph.cli --config config/graph.yaml
```
This runs Modules 1 and 2 first. Outputs go to `reports/graph/`: `network_report.md`, a network
chart per event, `account_trades_screened.csv`, `insider_links.csv`, and `graph.graphml`
(open it in [Gephi](https://gephi.org) to explore the network).

On the sample data it links three accounts to insiders: the CFO's spouse, a director's family
trust and a VP's sister. It also shows that the two ACME insiders sit on the same outside board.
A pension fund that bought before the news has no known link, and it is reported as such rather
than ignored.

## Module 4: LLM document review

> **Plain-language summary:** Enforcement teams read large numbers of documents. This module has
> an LLM read each one and fill in a standard form: who was charged, which company's shares, what
> conduct, which laws, what sanctions. It must quote the exact sentence behind every answer, and
> anything doubtful goes to a person. Its accuracy is **measured** against answers a human checked
> by hand, for two prompt versions and two models, together with what each costs.

**Test corpus:** public SEC litigation releases about insider trading, collected with a polite,
logged downloader and registered in the Module 1 custody log.

### Design choices (and why they matter for enforcement work)

| Choice | Why |
|---|---|
| **Structured outputs** with a schema generated from one Pydantic model | The API guarantees JSON in a fixed shape, and the same model validates it. The schema is adapted automatically to the API's rules. |
| **Verbatim evidence quotes + grounding check** | Every fact must point to a sentence found word for word in the source. Invented quotes are caught automatically. |
| **Human review queue** | Low confidence, ungrounded quotes, missing respondents or inconsistent dates all go to a person. The LLM assists; it does not decide. |
| **Versioned prompts** (`v1.0`, `v1.1`) | v1.1 adds field definitions (e.g. "sought" ≠ "ordered" sanctions; relief defendants). Every record names its prompt, and versions are compared on the same answer key. |
| **Gold labels with a written guide**, some labelled blind | The accuracy number is only as good as the answer key: see [docs/labeling_guide.md](docs/labeling_guide.md). |
| **Cost tracked per run** | Tokens × list price, so the "which model?" trade-off is explicit. |
| **Fingerprint (SHA-256) of every source + prompt version + model in each record; disk cache** | Chain of custody. Re-runs cost nothing and give identical outputs. |
| **Document treated as data** | The prompt tells the model to ignore instructions inside documents (prompt-injection guard). |
| **Tested against the real SDK** with a local stand-in server | Catches API changes (e.g. `temperature` and forced tool choice are rejected by current models) without spending money. |

### Workflow

```bash
pip install -e ".[dev]"
cp .env.example .env            # put your ANTHROPIC_API_KEY in .env, then:
set -a; source .env; set +a

# 1. Collect ~120 insider-trading releases (about 15-25 min at 1 request/second)
python -m enforcement_toolkit.extraction.cli fetch-sec --user-agent "Your Name you@example.com" --start 26694 --want 120

# 2. Dry run on 3 documents, then check data/processed/extraction/sonnet-v1.0/ before spending more
python -m enforcement_toolkit.extraction.cli extract --run sonnet-v1.0 --limit 3
python -m enforcement_toolkit.extraction.cli extract --run sonnet-v1.0

# 3. Label 50 documents (15 from blank first), following docs/labeling_guide.md
python -m enforcement_toolkit.extraction.cli label-prepare --from-run sonnet-v1.0
python -m enforcement_toolkit.extraction.cli label-status

# 4. Run the other configurations and compare everything against the labels
python -m enforcement_toolkit.extraction.cli extract --all
python -m enforcement_toolkit.extraction.cli compare     # -> reports/extraction/comparison.md
```

**Cost:** at list prices (Sonnet 5.5 $2 / $10, Haiku 5.5 $0.10 / $0.50 per million input / output
tokens), the full workflow on ~120 releases should cost **roughly $5–10**, almost all of it Sonnet.
Step 2's dry run prints the real token counts, so you can check before running the rest.

### Future work
- Chunked (map-reduce) extraction for very long documents, instead of truncating them.
- Message Batches API for large runs (half the price, results within 24 hours).
- Canadian corpus: Capital Markets Tribunal decisions (PDF).

## Continuous integration
Every push and pull request runs on GitHub Actions (`.github/workflows/ci.yml`): `ruff` lint and format checks,
then the test suite on Python 3.10–3.12, then a smoke run of validation, detection and the graph, whose reports are saved as build artifacts. The tests use a fake LLM client, so CI needs no API key and costs nothing.
