# Labelling guide: gold answers for Module 4

The gold labels are the answer key the LLM is scored against. If the labels are inconsistent, the
accuracy numbers mean nothing. So every label follows the rules below, which are the same field
definitions given to the model in prompt v1.1.

## Setup (VS Code)

1. Run `python -m enforcement_toolkit.extraction.cli label-prepare --from-run sonnet-v1.0`.
   This creates 50 files in `data/gold/labels/`. The first 15 are **blank**, and the rest are **pre-filled** from the model.
2. For each file, open the JSON and the matching text file side by side.
   The `source_text` field in the JSON gives the path. Right-click a tab → **Split Right**.
3. Fill in or correct `extraction`, write anything unusual in `_notes`, then set `"_reviewed": true`.
4. Run `label-status` regularly. It counts reviewed files and reports any label that breaks the schema.

**Label the 15 blank files first, before you look at any model output.** Pre-filled answers are
faster to check, but people tend to accept what's already there. Comparing accuracy on the blank
and pre-filled subsets shows whether that happened.

## Field rules

| Field | Rule | Example |
|---|---|---|
| `case_title` | The case caption as written | `"SEC v. Jane Q. Doe"` |
| `decision_date` | Date of **this release** (header), `YYYY-MM-DD` | `"2026-11-20"` |
| `respondents` | Everyone **charged or named as defendant/respondent**, full name as first written. Relief defendants are included with role `"relief defendant"`. **Not** victims, employers, witnesses or the SEC | `{"name": "Jane Q. Doe", "entity_type": "individual", "role": null}` |
| `securities` | Issuer(s) whose securities were traded or offered in the misconduct | `["Acme Mining Inc."]` |
| `conduct_types` | From the allowed list. `insider_trading` = trading on material non-public information; `tipping` = passing it on. Both can apply | `["insider_trading", "tipping"]` |
| `conduct_start` / `conduct_end` | Only if exact dates are stated, otherwise `null` | `"2024-06-04"` |
| `profit_or_loss_avoided` | The illicit profit or loss avoided from the trading. **Not** disgorgement or a penalty | `{"amount": 125000, "currency": "USD"}` |
| `sanctions` | Only sanctions **ordered, imposed or agreed in a settlement**. Not relief that was merely "sought" | `{"kind": "disgorgement", "respondent": "Jane Q. Doe", "amount": {"amount": 125000, "currency": "USD"}, "duration_years": null, "permanent": false}` |
| `legislation_cited` | Each provision named as violated, one per item | `["Section 10(b) of the Securities Exchange Act of 1934", "Rule 10b-5"]` |

Sanction kinds: civil penalty → `administrative_penalty`; disgorgement (with or without
prejudgment interest) → `disgorgement`; officer-and-director bar → `director_officer_ban`;
conduct-based or penny-stock bar → `trading_ban`; anything else → `other`.

## When unsure

- If the release doesn't say, use `null` or `[]`. **Never infer.**
- If two readings are reasonable, pick one, explain it in `_notes`, and apply the same choice every time.
- If a document is not really an insider trading case, label it anyway. The model has to handle mixed input too.

## Effort

About 50 documents at 3 to 5 minutes each, so 3 to 4 hours. You can stop at any point: `compare`
uses whatever has been reviewed. 20 documents already gives a useful first reading, but the
results are more reliable at 50.
