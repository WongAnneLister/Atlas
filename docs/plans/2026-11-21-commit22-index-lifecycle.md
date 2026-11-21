# Commit 22 plan — incremental ingestion, versioned index, eval-gated alias release

Spec: `docs/commits/22-incremental-ingestion.md`. This plan adapts it to the code as it is on `main` at `5536e70`.
It splits the work into three commits, as 20/20a and 21a/21/21b did:

| Commit | Who | Message |
|---|---|---|
| 22a | Codex | `feat(eval): index release check with paired retrieval and no-answer gate rules` |
| 22 | Codex | `feat(retrieval): incremental ingestion with change detection, versioned collections and eval-gated alias release` |
| 22b | author, after review | `chore(eval): index lifecycle evidence` |

22a comes first because of `AGENTS.md` §5.7: the eval that judges a feature lands before the feature.

## 0. What exists today (checked on 2026-11-21)

- `make ingest` runs `support_agent.ingest`. It chunks `data/processed/docs/*.md`, embeds every chunk, then **drops and recreates** the collection named by `milvus.collection`. It writes `data/processed/chunks.jsonl` and `ingest_run.json`.
- `chunk_id = digest(f"{section_id}:{index}")` (`retrieval/chunking.py`). The id depends on the section and the chunk's position, not on the text. So ids already stay stable for unchanged sections.
- The live Milvus server is 2.5.10 and pymilvus is 3.0.2. The collections are `support_chunks` (206 rows, the live token index), `support_chunks_eval_heading_on` (206), `support_chunks_eval_no_heading` (206) and `support_chunks_faq_v1` (870). **No aliases exist.**
- All four collections share the description `support-agent dense+BM25 chunks v1`. The description check (`_assert_owned`) cannot tell a release build from an eval collection.
- The app and every eval read `settings.milvus.collection`. `eval/chunking_ab.py` overrides it to read other collections by name.
- Production retrieval is `KnowledgeNodes.retrieve` → `knowledge_retriever().retrieve(rewritten_query, pool)` → `scope_chunks` → `gate.evaluate`. `eval/sweep.py::production_chunks` mirrors it on the raw question, with no LLM.
- Postgres (port **5433**, Atlas only) or the SQLite fallback hold orders through SQLAlchemy and Alembic (`migrations/versions/0001_orders.py`, `0002_refund_idempotency.py`).
- `eval/compare.py` and `eval/stats.py` already do paired comparisons (McNemar for booleans, bootstrap otherwise) with verdicts `better`, `worse` and `no significant change`. `eval/gate_rules.yaml` holds the metric rules.
- On CPU the reranker takes about 15–20 s per query (the red-team logs show 13 batches of 4 pairs). That cost shapes §1.6.

## 1. Decisions and deviations from the spec

Each one goes in the final message and in `docs/RETRIEVAL.md`.

1. **Every change builds a new collection.** There is no in-place edit of the live collection. The spec has two modes: an in-place upsert when the model and chunker are unchanged, and a new collection otherwise.
   - An in-place edit skips the release check, so a bad edit goes live at once. It also cannot be rolled back, because the old vectors are gone.
   - Here, both modes write `support_chunks_b<build_id>` and go live only through `index-release`.
   - The modes now differ only in **what gets embedded**:
     - *incremental* (same fingerprint as the live build): embed only added and changed sections, and copy the stored vectors of unchanged chunks from the live collection;
     - *full* (fingerprint changed): embed everything.
   - Cost: one extra collection of about 206 rows per change, and the new text is live only after the release check.
2. **The change plan compares the docs with the live build, not with the latest DB row.** A new table `build_sections` records which section versions each build holds.
   - So the plan stays correct after a rollback and after a build that was never released.
3. **A fingerprint decides incremental or full.** `fingerprint = digest(embedding model + revision + dim + normalize + window tokens + chunk settings + prepend_heading + CHUNKER_VERSION + STORE_SCHEMA_VERSION)`.
   - `CHUNKER_VERSION` is a constant in `retrieval/chunking.py`.
   - A golden test pins the chunk ids and texts for one fixture document. If the chunker output changes and the constant is not bumped, the test fails.
4. **The release check runs retrieval and the gate only. It makes no LLM calls.** It runs the same functions as production, on the raw question, as `make sweep` does.
   - It is deterministic and uses no API budget. It also tests the thing an index change can break: which chunks come back and how high they score.
   - The full-graph smoke and red-team gates stay in CI as they are. The difference between raw and rewritten queries is a known limit; write it down.
5. **The release has two kinds of rule.** Release only if all pass:
   - (a) **Absolute, fail-closed:** zero gate passes on every no-answer item in the release set, at the configured threshold. This rule has no override.
   - (b) **Paired against the live build:** no `worse` verdict on any blocking metric.
   - (c) **Invalid run:** if retrieval errors exceed `promotion_max_error_rate`, the run is reported as `Invalid run`, not as a regression.
6. **A recorded override exists only for rule (b).** `--override-reason "<text>"` is stored on the build row and printed in the release report. For example, a deleted policy section can lower recall on items whose gold labels point at it.
   - It never overrides rule (a). Gold labels are fixed in a separate commit, as `AGENTS.md` §5.1 requires.
7. **Bootstrap and adoption.** The alias is `support_chunks_live`, and `milvus.collection` in config becomes that alias.
   - `make index-adopt COLLECTION=support_chunks` registers an existing collection as a build. It reads its chunks back, checks that they match what the chunker produces from the docs on disk, records the build, and points the alias at it. If they do not match, it refuses.
   - Adoption runs no release check, because it describes what is already live.
   - On a fresh clone with no alias, `make ingest` builds and then releases with rule (a) only, because there is no live build to pair against. It prints the metrics.
8. **Garbage collection drops only registered, non-adopted builds whose names match `support_chunks_b<id>`, and never the live or previous target.**
   - The eval collections and `support_chunks` itself are never dropped.
   - Keep the count in config (`index.keep_builds: 2`).
9. **`make ingest` changes meaning.** It is now build + release, so a fresh clone still needs one command.
   - New targets: `index-plan`, `index-build`, `index-release BUILD=`, `index-rollback`, `index-status`, `index-adopt COLLECTION=` and `index-gc`.
   - `--docs-dir` lets a scratch copy of the docs be used. The freshness test and the 22b demo use it.
10. **Codex does not touch Milvus or the developer databases.** It writes the integration tests and does not run them, as in commit 21. The author runs them, and the live demo, in 22b.

## 2. Commit 22a — the release check (eval first)

### 2.1 `eval/index_release.py` (new)
- **Input:** a collection name (or alias), a release set, and the current settings.
- **Release set:** dev answerable and dev no-answer items, plus the smoke items. Configure it under `index.release.sets`, default `[dev, smoke]`.
  - Use the item loaders that `make sweep` and `make eval-smoke` already use. Do not copy item lists.
- **Per item:** call `eval.sweep.production_chunks(retriever, item.question, settings)`, then `gate.evaluate`. Move `production_chunks` to a shared module if a clean import needs it; do not duplicate it.
- **Record booleans per item, so the compare uses McNemar:**
  - `hit_at_5`: any gold section in the top five, answerable only;
  - `gate_pass`: answerable only;
  - `noanswer_gate_pass`: no-answer only.
- **Record one number per item, compared by bootstrap:** `rr_at_5`.
- **Record for drill-down, not for blocking:** the gate score and the top chunk ids.
- **Write a run record** with `kind: index_release` in `eval/runs/index-release-<split>-<date>-<sha>-<suffix>/`, using `eval/run_record.py`.
  - The manifest `source` holds the collection, the build id (or `null` before commit 22), the fingerprint, and the item-set hash.
- **Reuse:** if a run for the same build id, item-set hash and retrieval/gate config hash already exists, the release step reuses it for the live side instead of rerunning. This halves the time, because the reranker is slow on CPU.
- **Device:** allow `--reranker-device` to override `retrieval.reranker_device` for this run only, and record the device in the manifest.

### 2.2 Rules
- Add the new metrics to `eval/gate_rules.yaml` with explicit directions:
  - `hit_at_5`, `rr_at_5` and `gate_pass`: higher is better, blocking;
  - `noanswer_gate_pass`: lower is better, blocking.
- Add `index_release: {noanswer_gate_pass_max: 0}` as the rule-(a) setting.
- Write a comment above the block saying it was registered before any 22b run, as with the red-team budgets.
- `eval/index_release.py check <candidate_run> --live <live_run>` returns a decision object with three outcomes:
  - `release`;
  - `refuse` with reasons: each failing rule, and per metric the items that changed;
  - `invalid`: an error rate over the limit.
- Render it to markdown. The CLI exits 0 only on `release`.

### 2.3 Tests (offline)
Use a fake store with `FakeEmbedder` and `FakeReranker` from `src/support_agent/retrieval/`. Cover:
- identical runs give `release`;
- one no-answer item passing the gate gives `refuse`, even when everything else is better;
- a paired `worse` on `hit_at_5` gives `refuse` with the item ids listed;
- an override reason clears rule (b) but not rule (a);
- an error rate over the limit gives `invalid`;
- live-side reuse happens only when all three keys match.

### 2.4 Docs for 22a
- PROGRESS row 22a.
- Note `docs/notes/22-index-release-check.md` with "No number yet. I will measure it in commit 22b."
- Include this plan file in the commit.

## 3. Commit 22 — the lifecycle

### 3.1 Registry tables (`migrations/versions/0003_index_registry.py`)
The tables use the same database and migration chain as orders, so they work on Postgres and the SQLite fallback. Use `sa.JSON`, not a Postgres-only type.
- `documents(doc_id PK, title, source, version, updated_at)`.
- `sections(section_id, version, doc_id, content_hash, text, metadata JSON, is_deleted, created_at)`, with PK `(section_id, version)`.
  - A new version is written only when the content hash changes.
  - A deleted section gets a row with `is_deleted = true`.
- `index_builds(build_id PK, collection UNIQUE, mode: full|incremental|adopted, fingerprint, embed_model, embed_revision, chunker_version, docs_hash, parent_build_id, status, eval_run_id, override_reason, created_at, released_at)`.
  - `status` is one of `building`, `built`, `failed`, `released`, `retired` or `dropped`.
- `build_sections(build_id, section_id, section_version, content_hash, chunk_count)`, with PK `(build_id, section_id)`.
- `index_alias(alias PK, build_id, previous_build_id, updated_at)`: one row, the history of record for the alias.
- Repository code goes in `src/support_agent/retrieval/registry.py`. It holds the SQLAlchemy Core queries, the way the orders repository is written.

### 3.2 Change plan (`retrieval/index_plan.py`)
- Parse the docs folder with the existing `parse_document`. For each section, compute `content_hash = digest(heading + text + metadata that the chunker reads)`.
- Compare with the live build's `build_sections` (none at bootstrap). Return a Pydantic plan with `added`, `changed`, `deleted` and `unchanged` lists of section ids, the fingerprints of the live build and the docs, and the mode.
- `make index-plan` prints it and writes nothing. It must work with no Milvus connection.

### 3.3 Build (`retrieval/index_build.py`)
1. Create the registry row with `status=building` and a new collection `support_chunks_b<build_id>`.
   - Create it with the same schema code as `create_or_reset`. Split the schema creation out, and let `create_or_reset` refuse an alias name.
2. **Full mode:** chunk and embed everything.
   **Incremental mode:**
   - chunk only the added and changed sections, and embed only those chunks;
   - read the unchanged sections' rows from the live collection, filtered by `section_id in [...]`, with the `dense` field;
   - insert them unchanged. BM25 sparse vectors are rebuilt by the Milvus function on insert.
3. Verify the result:
   - the count equals the expected chunk count;
   - every unchanged chunk id is present with a bit-identical dense vector;
   - no chunk of a deleted section is present.
4. Write the `sections` versions and the `build_sections` rows **in the same transaction** that sets `status=built`. On any failure, set `status=failed` and drop the new collection.
5. Write `data/processed/builds/<build_id>/chunks.jsonl`.
   - `data/processed/chunks.jsonl` stays "the chunks of the last build". Record its build id in `ingest_run.json`.
   - Readers that join chunk ids with local text, such as the sweep cache, must check that build id. Find each reader, and fail loudly on a mismatch.

### 3.4 Release, rollback, status, GC (`retrieval/index_release.py` in `src`, calling the 22a check)
- **`index-release BUILD=<id>`:**
  - run the 22a check on the candidate collection, reusing the live run if allowed;
  - on `release`, call `alter_alias` (or `create_alias` at bootstrap) on Milvus;
  - then update `index_alias` with a compare-and-set on the expected current build;
  - set the statuses: new build `released`, old build `retired`;
  - store `eval_run_id` on the build.
  - On `refuse` or `invalid`: print the report, change nothing, and exit non-zero.
- **`index-rollback`:** point the alias at `previous_build_id`, but only if that collection still exists. Record the swap in `index_alias`. It runs no eval, because the previous build was released before.
- **`index-status`:** shows the alias target according to Milvus and according to the DB, plus the builds. It reports **drift**, a mismatch between the two (for example after a crash between the Milvus call and the DB write). `index-status --reconcile` writes the Milvus truth into the DB.
- **`index-gc`:** applies §1.8. It prints what it would drop, and drops only with `--yes`.
- **Locking:** release, rollback and GC hold one lock for their whole run. Use a DB row lock on `index_alias` (`SELECT … FOR UPDATE` on Postgres; SQLite's write lock from `BEGIN IMMEDIATE`), the same pattern as the refund guard. Two concurrent releases must not both switch the alias.

### 3.5 App and eval reads
- `milvus.collection: support_chunks_live` (the alias).
- Search through an alias works in Milvus. Check `has_collection` and `describe_collection` against an alias in the integration test, and do not assume. Readiness (`/ready`) must report a missing alias as not ready.
- `current_build_id()`:
  - resolves the alias with `describe_alias` and maps the collection to its build id through the registry, or through the name pattern;
  - caches the result in process for `index.alias_ttl_s` (config);
  - returns `None` when not resolvable, and the knowledge path keeps working.
- Record the build id in:
  - the retrieval snapshot that goes into handoff payloads;
  - the trace;
  - the `source` of e2e, smoke, red-team and retrieval run manifests. `AGENTS.md` §5.1 says reports record what they ran on.
- Metrics label: none. Build ids are not low-cardinality enough to be worth it.

### 3.6 Freshness integration test (`tests/test_index_freshness_integration.py`, `@pytest.mark.integration`, next to `tests/test_milvus_integration.py`)
- It uses a unique collection prefix and alias per run (`atlas_test_<uuid>_…`) and a scratch registry DB (a temporary SQLite file, or a scratch database on port 5433 when `ATLAS_TEST_PG_URL` is set). It never touches `support_chunks_live` or `support_chunks`.
- It uses a scratch copy of the docs and the real Milvus. Use `FakeEmbedder` (`retrieval/embed.py`) and `FakeReranker` (`retrieval/rerank.py`), so the test needs no model weights.
- Steps:
  1. Pick a real policy section that states a day count. Look it up; do not assume "30".
  2. Build and release.
  3. Edit the copy to a new number, run the plan, and assert it is exactly `changed=[that section]`.
  4. Build incrementally. Assert that the embedder was called only for that section's chunks and that the other rows were copied bit for bit.
  5. Release. Retrieval for the question now returns the new text and never the old.
  6. The knowledge node, with `FakeListChatModel` citing `[1]`, cites a chunk whose text holds the new number.
  7. Roll back. The old text is back.
  8. Delete a section. After the next build and release, a search finds none of its chunks.
- Drop every test collection and alias in a `finally` block.

### 3.7 Docs
- `docs/RETRIEVAL.md`: a new section "Index lifecycle" with a mermaid or ASCII diagram (build → check → alias switch → rollback), the §1 decisions, the raw-query limit, and the CPU cost of the check.
- `README` setup commands, if they mention `make ingest`.
- PROGRESS row 22.
- Note `docs/notes/22-incremental-ingestion.md` with "No number yet. I will measure it in commit 22b."

## 4. Tests for commit 22 (offline unless marked; add, never weaken)

- Change plan on fixtures: added, changed, deleted, unchanged, and a heading-only change (a change).
- Fingerprint: the same settings give the same value. Any listed field, or a `CHUNKER_VERSION` bump, gives a new one. The golden chunk test is in place.
- Incremental build with an in-memory fake Milvus client:
  - the embed count equals the changed sections' chunk count;
  - copied vectors are identical;
  - deleted sections are absent;
  - unchanged chunk ids are stable;
  - a failure mid-build drops the new collection and marks the build `failed`.
- Release:
  - a fake check returning `refuse` leaves the alias as it was;
  - `release` switches it and records `previous_build_id`;
  - the override path is recorded;
  - the compare-and-set fails cleanly if another release won.
- Rollback restores the previous target. Rollback with no previous build, or with a dropped one, refuses.
- GC never drops the live target, the previous target, adopted builds, or unregistered collections.
- Adoption refuses a collection whose chunks do not match the docs on disk.
- `create_or_reset` refuses an alias name.
- Readiness reports a missing alias.
- `current_build_id()` TTL behaviour, and `None` on failure.
- Run manifests carry the build id.
- The migration upgrades and downgrades on SQLite in tests. The Postgres run is part of the integration suite.
- Integration (not run by Codex): §3.6, and an alias smoke test (`has_collection`, `describe_collection` and search through an alias).

## 5. Order of work (each step ends with `make check` green)

1. 22a: `eval/index_release.py`, rules, tests, plan file, PROGRESS row 22a, note → commit 22a.
2. Migration and registry.
3. Change plan and fingerprint.
4. Build (full and incremental), schema split, local chunk files.
5. Release, rollback, status, GC, locking, adoption.
6. Alias reads, `current_build_id()`, manifests, readiness.
7. Integration tests (written, not run), docs, Make targets, PROGRESS row 22, note → commit 22.

## 6. Evidence commit 22b (the author runs it after review)

1. Run the integration tests against Milvus and the Postgres on port 5433, with scratch prefixes and a scratch database.
2. `make index-adopt COLLECTION=support_chunks`: the alias now points at today's collection.
3. **Identical rebuild:** run a full build with the same settings, then `index-release`. Expect `release` with no significant change. If the run differs, record whether the embedder is deterministic on CPU.
4. **Negative control:** run the 22a check on `support_chunks_eval_no_heading` against the live run. Report whether it refuses, and why. Do not choose this control's expected result after seeing it.
5. **One-section change on a scratch docs copy:**
   - record the plan, the embed count against the full count, and the build time incremental against full;
   - release, ask the question in the real app, and see the new text cited;
   - `index-rollback`, ask again, and see the old text.
   - Leave the alias on the build from step 3.
6. **Report** `eval/reports/index_lifecycle.md`. Generate it with a script from the run records and registry rows; type no numbers by hand.
7. PROGRESS row 22b, a verification section, note `docs/notes/22-index-lifecycle-evidence.md`, then the commit.

## 7. Do not

- Do not run anything that calls an LLM, Milvus, or the developer databases (Codex). Do not use port 5432.
- Do not drop or modify `support_chunks`, the `support_chunks_eval_*` collections or `support_chunks_faq_v1`.
- Do not change eval questions, gold labels, `smoke.yaml: item_ids`, `eval/baselines/main.json`, the gate threshold or the red-team budgets.
- Do not add frameworks or dependencies. The alias API is in pymilvus 3.0.2.
- Do not start policy validity dates (23) or caching (26). Do not push.

## 8. Final message

Say what changed in 22a and 22, how you verified each, every deviation from the spec and from this plan, and the follow-ups.
Then paste both interview notes in full.
