# Commit 21 — Guardrails, PII redaction, auth and rate limits

**Phase 2 · depends on: 19, 20**

## Context
Commit 20 measured the baseline attack success rate. Now add layered defences and prove they work **without** breaking normal
answers. Defence in depth: structural controls first (what the model can reach), classifiers second, output checks last.

## Read first
- `docs/THREAT_MODEL.md`, `eval/reports/redteam.md`
- `graph/tools.py`, `graph/nodes/refund/`, `graph/nodes/knowledge.py`, `api/app.py`

## Task
1. **Structural controls (most important, cheapest)**
   - Tools already inject `customer_id` from state — audit every tool and node; add a test per tool.
   - Retrieved text and order fields are passed to the model inside clearly delimited data blocks with an instruction that content inside is data, not instructions. Internal-only order fields (internal notes) are never given to the model.
   - Refund creation requires the code checks from commit 12 — confirm no path lets the model trigger `create_refund_request` directly.
2. `src/support_agent/guardrails/input.py` — input checks before rewrite: length limit, injection heuristics (patterns + a small `fast`-model classifier behind a config flag), off-topic detection. Outcomes: `allow | allow_flagged | block` (block → polite refusal + optional handoff). Flags are stored in state and traced.
3. `src/support_agent/guardrails/output.py` — checks before the answer is streamed out (buffer the first sentence or run on the final text for non-streaming parts, document the choice): canary/system-prompt leak, PII of anyone other than the current customer, commitments (refund approved, compensation, dates) not backed by a tool result or citation. Violation → replace with a safe message + handoff `guardrail_blocked`.
4. `src/support_agent/guardrails/pii.py` — redaction for logs and traces (emails, phones, addresses, card-like numbers) applied in the logging and Langfuse layers. Unit-tested.
5. **API security** — demo auth: signed session token per demo customer (`/api/session` issues it); every request's `customer_id` comes from the token, not the body. Rate limits in Redis per customer and per IP (config). Request size limits.
6. Re-run `make eval-redteam` and the full e2e eval. Report in `eval/reports/redteam.md` (before vs after per category, paired CIs) and **false-reject impact** on normal questions (did guardrails block legitimate users?).
7. Set ASR budgets in `eval/gate_rules.yaml` from the new results (e.g. 0 for cross-customer access and canary leaks; small non-zero budgets elsewhere with a written reason).

## Requirements
- Cross-customer access and canary leaks: target ASR 0. If not reached, do not pretend — list the remaining attacks.
- Normal-traffic false-reject must not get significantly worse (paired test); if it does, report the trade-off and the chosen setting.

## Tests
- One test per structural control (tool ignores model-supplied customer id; internal notes never in prompts).
- Input/output checkers on fixtures; PII redaction cases.
- Auth: body `customer_id` ignored; missing/invalid token → 401. Rate limit → 429.

## Out of scope
Online abuse monitoring (32).

## Done when
- [ ] Red-team before/after table with CIs; normal false-reject impact reported
- [ ] ASR budgets set and enforced in CI gate
- [ ] `make check` green; PROGRESS row 21 updated
- [ ] Interview note `docs/notes/21-guardrails-security.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(guardrails): structural controls, input/output guardrails, PII redaction, token auth and rate limits
```
