# Commit 16 — English README, results, demo script

**Week 4 · depends on: everything before** · this is the Week 4 checkpoint (**repo public + demo video**)

## Context
The real audience is an overseas interviewer who spends 3 minutes on the repo. In that time they must see:
what it does, that it is safe (0% false-accept), that decisions are backed by numbers, and how to run it.
Every number in the README must come from `eval/reports/` (AGENTS §5.1).

## Read first
- `docs/PRD.md`, `docs/RESULTS.md`, `docs/RETRIEVAL.md`, `docs/INTENTS.md`, `docs/REFUND_FLOW.md`, `docs/LICENSES.md`, `docs/PROGRESS.md`
- All files in `eval/reports/`

## Task
1. `scripts/render_results.py` + `make results` — reads the latest reports and writes the results block of the README between markers
   `<!-- RESULTS:START -->` / `<!-- RESULTS:END -->` (tables + report links). The README text around it is hand-written; the numbers are generated.
2. `README.md` (English, plain and short sentences), sections in this order:
   1. **One-line pitch** + a GIF/screenshot placeholder (`docs/img/demo.gif`) + link to the video (placeholder URL for the human).
   2. **Results at a glance** (generated): test-split false-accept, false-reject, Recall@5, MRR, intent accuracy, hallucination (judge-flagged / human-confirmed or "pending"), P50/P95 latency, cost per conversation.
   3. **Architecture** — Mermaid diagram: rewrite → classify → 5 paths; the knowledge path shows retrieve → rerank → gate → answer/handoff; the refund path shows the interrupt.
   4. **Design decisions & trade-offs** — 4–6 short entries, each "Decision / Why / Evidence (link to report) / Cost of this choice". Must include: workflow vs free agent; hybrid + RRF vs single retriever; gate before generation; how the threshold was chosen (dev sweep, test report, false-reject price); dev/test split; facts from tools vs rules from retrieval in refunds.
   5. **Quick start** — prerequisites, `.env`, `make setup up data ingest serve`, expected time, disk use for models.
   6. **Reproduce the numbers** — `make eval-retrieval sweep eval-e2e eval-judge`, and where reports land.
   7. **Data & licenses** — the three datasets with links and license verdicts; what is synthetic (orders, cross-doc and no-answer questions); limitations.
   8. **Limitations & next steps** — honest list (synthetic data, English only, no auth, P1 items not done).
   9. **Project layout** — short tree.
3. `docs/DEMO_SCRIPT.md` — a 2-minute video script for the human to record, with exact messages to type and what to point at:
   (0:00) one-line intro → (0:15) policy question with citations + debug panel showing the gate score → (0:45) model-number question showing exact match →
   (1:05) "I want a refund for my last order" → picker → decision with citations → (1:35) "Can I pay with gold bars?" → handoff with reason →
   (1:50) README results table. Pick customer ids and order ids from `docs/ORDERS.md` that produce these outcomes, and **verify each message on the running app** before writing it down.
4. Check that a fresh clone works: follow Quick start in a clean directory (or a container) and fix any gap in the README.
5. Repo hygiene: GitHub description + topics suggestion in `docs/REPO_SETTINGS.md` (the human applies them), issue templates not needed.

## Requirements
- No metric typed by hand anywhere in README; `make results` regenerates it.
- No mention of any other company's numbers. This project's results only.
- Plain English: short sentences, no hype words ("revolutionary", "cutting-edge").

## Tests
- `render_results.py` on fixture reports writes the expected block and is idempotent.
- A test that fails if README contains a percentage outside the generated block (simple regex), to keep numbers honest.

## Out of scope
Recording the video, making the repo public — the human does these.

## Done when
- [ ] `make results` fills README; Quick start verified on a clean clone
- [ ] `docs/DEMO_SCRIPT.md` verified on the running app
- [ ] `make check` green; PROGRESS row 16 updated; **Checkpoint 4** waits for the human (repo public + video link added)
- [ ] Interview note `docs/notes/16-readme-demo.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
docs: English README with generated results, architecture, trade-offs and demo script
```
