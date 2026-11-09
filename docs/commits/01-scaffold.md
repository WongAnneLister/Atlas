# Commit 01 — Project scaffold

**Week 1 · depends on: nothing**

## Context
This is an English e-commerce after-sales support agent (LangGraph + hybrid RAG + evidence gate).
The repo currently contains only `AGENTS.md` and `docs/`. You are creating the skeleton every later commit builds on.

## Read first
- `AGENTS.md` (all of it — stack, layout, rules)
- `docs/PRD.md` sections "Scope" and "System design"

## Task
Create a runnable, empty-but-wired Python project.

1. **Packaging** — `pyproject.toml` for `uv`, Python 3.11, package `support_agent` under `src/`.
   Runtime deps: `langgraph`, `langchain`, `langchain-core`, `pydantic>=2`, `pydantic-settings`, `pyyaml`, `fastapi`, `uvicorn[standard]`, `sse-starlette`, `pymilvus`, `FlagEmbedding` (or `sentence-transformers`), `datasets`, `httpx`, `structlog`.
   Optional extras: `[tracing]` → `langfuse`; provider extras left to the user (e.g. `langchain-openai`, `langchain-anthropic`).
   Dev deps: `pytest`, `pytest-asyncio`, `ruff`, `mypy`, `pre-commit`, `matplotlib`.
2. **Config** — `configs/default.yaml` with every knob the PRD mentions, grouped:
   `llm` (fast/main model names, temperature), `retrieval` (dense_top_k: 50, bm25_top_k: 50, rrf_k: 60, rerank_top_k: 5, models),
   `gate` (weights: top_score 0.5, good_count 0.2, margin 0.15, key_hit 0.15; good_evidence_min; threshold: null — set by sweep),
   `agent` (max_steps: 5), `milvus` (uri, collection), `orders` (db_path, seed), `memory` (P1 placeholders), `tracing` (enabled: false).
   `src/support_agent/config.py`: a typed `Settings` (pydantic) loading YAML, overridable by env vars (`SUPPORT_AGENT__RETRIEVAL__RRF_K=...`). Expose `get_settings()` (cached).
3. **LLM factory** — `src/support_agent/llm.py` with `get_chat_model(role: Literal["fast","main"])` using `init_chat_model` and env vars `LLM_FAST_MODEL`, `LLM_MAIN_MODEL`, `LLM_PROVIDER`. Add a test hook to inject a fake model.
4. **Empty package modules** matching the layout in `AGENTS.md` §3, each with a module docstring saying what will live there.
5. **Docker** — `docker-compose.yml` with Milvus standalone (etcd + minio + milvus, version ≥ 2.5 so BM25 full-text search is available). Langfuse services under a compose profile `tracing` so they do not start by default.
6. **Makefile** — targets from `AGENTS.md` §4. Targets whose code does not exist yet print `"not implemented yet (commit NN)"` and exit 0.
7. **Quality** — ruff (lint + format) and mypy config in `pyproject.toml`; `.pre-commit-config.yaml`; pytest config registering the `integration` marker and skipping it unless `-m integration`.
8. **CI** — `.github/workflows/ci.yml`: uv install, `make check` on push/PR. No secrets, no Docker.
9. **Interview-note pipeline** (AGENTS.md §9, `docs/notes/TEMPLATE.md`):
   - `scripts/check_notes.py` + `make notes-check` (also run inside `make check`). For every `docs/notes/NN-*.md` except `TEMPLATE.md`:
     the five headings exist in order (`What`, `Why`, `Number`, `Trade-off`, `Likely follow-up question` with `Q:` and `A:`);
     each section has 2–4 sentences; **no sentence over 15 words** (report the offending sentence);
     banned words (`leverage, utilize, robust, seamless, cutting-edge, state-of-the-art, synergy, holistic`) are absent;
     the Number section has either a `Source:` line pointing to an existing file or the exact phrase `No number yet`;
     **every number in the Number section appears in the cited source file** (simple string match on digits, `%` and decimals).
   - It also fails if a commit row in `docs/PROGRESS.md` is marked `done` but its note file is missing.
   - `make notes` — concatenates all notes in order into `docs/INTERVIEW_NOTES.md` (one file to review before interviews). Generated; committed.
   - Unit tests for the checker with good and bad fixture notes.
   - Write the note for **this** commit (01) as the first real note.
10. **Hygiene** — `.gitignore` (data/raw, *.sqlite, .env, model caches, __pycache__, .venv), `.env.example` with every env var and a comment, `LICENSE` (MIT), a 10-line placeholder `README.md`.

## Requirements
- `make setup && make check` passes on a clean clone with no network access after install.
- `python -c "from support_agent.config import get_settings; print(get_settings().retrieval.rrf_k)"` prints `60`.
- No hard-coded numbers outside `configs/default.yaml`.

## Tests
- `tests/test_config.py`: loads defaults; env override works; gate weights sum to 1.0 (add a validator that enforces it).
- `tests/test_llm.py`: `get_chat_model` returns the injected fake when the test hook is set; raises a clear error when env vars are missing.

## Out of scope
Any data download, retrieval, graph, or API code.

## Done when
- [ ] `make check` green locally
- [ ] `docker compose up -d` brings Milvus up healthy (try it if Docker is available; otherwise say you could not)
- [ ] `docs/PROGRESS.md` row 01 = done
- [ ] Interview note `docs/notes/01-scaffold.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
chore: scaffold project with config, LLM factory, Milvus compose and CI
```
