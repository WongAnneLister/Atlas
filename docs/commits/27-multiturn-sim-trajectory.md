# Commit 27 — Multi-turn user simulator, scenario suite and trajectory metrics

**Phase 2 · Evals · depends on: 17, 21** · eval first: this suite judges context management and memory (28–30)

## Context
Single-turn evals cannot see the failures that matter in support: forgetting the order id from 8 turns ago, re-asking for
information, losing the thread after a topic switch, calling the wrong tool, or looping. We need **conversation-level**
evaluation: a simulated customer with a goal, a scripted set of facts, and checks on both the outcome and the path (trajectory).

## Read first
- `docs/EVAL_PLATFORM.md`, `docs/REFUND_FLOW.md`, `docs/ORDERS.md`
- `api/app.py` (drive conversations through the API layer, including interrupts)

## Task
1. **Scenario format** — `eval/sets/scenarios_v1.jsonl` (registered). Each scenario:
   `id, category, customer_id, persona (tone, verbosity, patience), goal, facts (what the user knows: order id, item, dates, what they tried), hidden_info (only revealed if asked), script_hints (e.g. "switch topic at turn 4, come back at turn 8"), expected_outcome (answer | refund_created | refund_denied | handoff:<reason>), expected_tool_calls (set or sequence), max_turns, success_checks`.
2. **≥ 60 scenarios** across categories: simple policy Q&A; order status; refund eligible / not eligible / needs human; order picker interrupt; topic switch and return; user corrects themselves ("sorry, I meant order 1043"); long conversations (25–30 turns with filler); frustrated user → complaint handoff; mixed knowledge + order questions; the 3 multi-turn red-team attacks.
   Draft with an LLM, but every scenario's expected outcome must be derivable from `docs/ORDERS.md` + docs (check with a script where possible) and is human-reviewed via the review CSV workflow.
3. **User simulator** — `eval/sim/user.py`: an LLM role-plays the customer from the scenario (prompt `eval/prompts/user_sim.md`): stays in persona, reveals hidden info only when asked, never invents facts outside `facts`, follows script hints, outputs `[DONE]` when the goal is met or patience runs out. Separate model/temperature from the agent (config). Seeded for reproducibility where the provider allows.
4. **Runner** — `eval/sim/run.py` + `make eval-sim`: drives the agent via the API layer, handles order-picker interrupts by letting the simulator choose, records the full transcript, trace, tool calls, token usage per turn.
5. **Metrics** (`eval/sim/metrics.py`):
   - `task_success` (expected outcome reached, code-checked),
   - `tool_call_precision/recall` vs expected calls, `wrong_customer_access` (must be 0),
   - `turns_to_success`, `redundant_questions` (agent asks for info already given — judge + string checks on known facts),
   - `fact_retention` (at checkpoints the simulator asks about earlier facts; agent must use them correctly),
   - `loop_rate` (same tool call with same args ≥ 3 times), `handoff_appropriateness` (handoff when expected, not otherwise),
   - tokens per turn curve (input tokens vs turn index) — the baseline for commit 28.
6. **Simulator validity** — run each scenario 3× and report variance; manually review 10 transcripts and record in `eval/reports/sim_validity.md` whether the simulator stayed in role (simulator errors must be separated from agent errors).
7. Add a 10-scenario fixed subset to the CI eval gate (nightly only; it is expensive).

## Requirements
- The simulator never sees the agent's internal state, only its messages.
- Report the baseline honestly — this is v1's multi-turn quality before context work.

## Tests
- Success checkers and trajectory metrics on hand-written transcript fixtures.
- Runner with a fake agent and a fake simulator completes, handles an interrupt, stops at `max_turns`.

## Out of scope
Fixing what it finds (28–30).

## Done when
- [ ] `eval/reports/sim.md` baseline: task success, fact retention, redundant questions, tokens-per-turn curve, with CIs
- [ ] Simulator validity note written
- [ ] `make check` green; PROGRESS row 27 updated
- [ ] Interview note `docs/notes/27-multiturn-sim-trajectory.md` written per AGENTS.md §9 (5 questions, simple English), `make notes-check` green, note pasted in your final message

## Commit message
```
feat(eval): multi-turn user simulator, 60-scenario suite and trajectory metrics with baseline report
```
