# Commit 02 — Download datasets and check licenses

**Week 1 · depends on: 01**

## Context
Three public Hugging Face datasets feed this project (see `docs/PRD.md` → Data):
- `qgyd2021/e_commerce_customer_service` — main knowledge base (FAQ + product info)
- `MakTek/Customer_support_faqs_dataset` — extra FAQs (~200)
- `bitext/Bitext-customer-support-llm-chatbot-training-dataset` — 27 intents, ~27k utterances (intent + colloquial phrasing)

Before anything uses them we need them on disk, pinned, and their licenses written down.

## Read first
- `AGENTS.md` §5.3 (data and licenses)
- `src/support_agent/config.py`

## Task
1. `src/support_agent/data/download.py` + `make data-download`:
   - Downloads each dataset into `data/raw/<name>/` (parquet or jsonl), **pinned to a revision/commit hash** stored in `configs/default.yaml` under `data.sources`.
   - Idempotent: skips if already present with the same revision.
   - Writes `data/raw/MANIFEST.json`: name, revision, row counts per split, columns, sha256 of files, download date.
2. **Inspect, don't assume.** For each dataset print the real schema and 3 sample rows. Some datasets may contain non-English rows or multiple subsets/configs — find out and record which subset/columns we will use.
   Write findings to `docs/DATA_NOTES.md`: subsets, columns, language, row counts, quirks (duplicates, empty answers, HTML), and which fields map to what we need (FAQ question, FAQ answer, product name/model, product attributes, intent label, utterance).
3. `src/support_agent/data/licenses.py` + `make data-licenses`:
   - Reads each dataset card's license metadata via `huggingface_hub` (`DatasetCard` / `dataset_info`).
   - Writes `docs/LICENSES.md`: dataset, license id, link, "may we redistribute processed text in a public repo?" (yes / no / unclear), and what we will do (commit processed docs vs. ship scripts only).
   - If the license is missing or unclear → mark **unclear** and default to "scripts only". Do not guess.
4. Update `make data` to run download + licenses (later commits will append steps).

## Requirements
- No dataset files committed. `data/raw/` stays gitignored.
- Network code lives only in `download.py` / `licenses.py`; everything else reads local files.
- Clear error if the user has no network or HF is down.

## Tests
- Unit test the manifest writer and the "skip if same revision" logic using a temp dir and a fake loader (no network).
- Unit test the license classifier on a few fake card metadata dicts (MIT, CC-BY-4.0, CC-BY-NC, missing).

## Out of scope
Cleaning, merging into policy docs (commit 03), intent mapping (commit 09).

## Done when
- [ ] `make data-download` works on a real machine and `MANIFEST.json` exists
- [ ] `docs/DATA_NOTES.md` and `docs/LICENSES.md` written from real inspection
- [ ] `make check` green; PROGRESS row 02 updated with row counts and license verdicts
- [ ] Interview note `docs/notes/02-data-download.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(data): download pinned datasets, write manifest, data notes and license report
```
