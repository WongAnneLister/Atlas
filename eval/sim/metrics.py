"""Code-checked trajectory metrics, repeat variance, and tokens-per-turn curve."""

from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from collections.abc import Callable
from typing import Any

from eval.sim.models import ConversationTranscript, Scenario, ScenarioEvaluation, SimTurn
from eval.stats import bootstrap_ci, wilson_interval

_ASK_ORDER_ID = re.compile(
    r"\b(?:order\s*(?:id|number|#)|which\s+order|provide\s+(?:your\s+)?order)\b",
    re.IGNORECASE,
)
_ORDER_ID_TOKEN = re.compile(r"\bORD-\d+\b", re.IGNORECASE)

RedundancyJudge = Callable[[str, str, list[str]], bool]


def _canonical_tool_call(name: str, args: dict[str, Any]) -> str:
    return f"{name}:{json.dumps(args, sort_keys=True, separators=(',', ':'), ensure_ascii=False)}"


def _check_outcome(scenario: Scenario, transcript: ConversationTranscript) -> bool:
    turns = transcript.turns
    if not turns:
        return False
    checks = scenario.success_checks
    all_agent_text = "\n".join(turn.agent_message for turn in turns)
    lower_text = all_agent_text.lower()

    for required in checks.required_substrings:
        if required.lower() not in lower_text:
            return False
    for forbidden in checks.forbidden_substrings:
        if forbidden.lower() in lower_text:
            return False
    if checks.expect_interrupt and not any(turn.interrupt_prompt is not None for turn in turns):
        return False
    if checks.require_citations and not any(turn.citations for turn in turns):
        return False

    refund_created = any(turn.refund_request_id is not None for turn in turns)
    handoff_reasons = [turn.handoff_reason for turn in turns if turn.handoff_reason]

    expected = scenario.expected_outcome
    if expected == "refund_created":
        if not refund_created:
            return False
    elif expected == "refund_denied":
        if refund_created or not _denied_then_only_later_handoffs(turns):
            return False
        if not all_agent_text.strip():
            return False
    elif expected.startswith("handoff:"):
        target_reason = expected.split(":", 1)[1]
        if target_reason not in handoff_reasons:
            return False
    elif expected == "answer":
        if not all_agent_text.strip() or handoff_reasons:
            return False
    else:
        return False

    if checks.expect_refund_created and not refund_created:
        return False
    return not (
        checks.expect_handoff_reason and checks.expect_handoff_reason not in handoff_reasons
    )


def _turn_route(turn: SimTurn) -> list[str]:
    """The nodes of this turn only: the thread trace after its last input guard."""
    starts = [i for i, step in enumerate(turn.route) if step == "input_guard"]
    return turn.route[starts[-1] :] if starts else list(turn.route)


def _denied_then_only_later_handoffs(turns: list[SimTurn]) -> bool:
    """A refusal turn, and no handoff before it.

    After a correct refusal, a handoff for any reason passes the customer's next request
    to a human; it does not undo the refusal. 12c counted only customer-requested ones,
    which failed sim-024, where the customer then asked for an exception that no policy
    covers. The author chose this rule on 2026-11-28.
    """
    denial = next(
        (
            index
            for index, turn in enumerate(turns)
            if "refund_act" in _turn_route(turn)
            and turn.handoff_reason is None
            and turn.refund_request_id is None
        ),
        None,
    )
    if denial is None:
        return False
    return all(turn.handoff_reason is None or index > denial for index, turn in enumerate(turns))


def _tool_precision_recall(
    expected: list[str], observed: list[str]
) -> tuple[float | None, float | None]:
    if not expected and not observed:
        return None, None
    exp_set = set(expected)
    obs_set = set(observed)
    precision = len(exp_set & obs_set) / len(obs_set) if obs_set else (1.0 if not exp_set else 0.0)
    recall = len(exp_set & obs_set) / len(exp_set) if exp_set else None
    return precision, recall


def _count_redundant_questions(
    transcript: ConversationTranscript,
    *,
    judge: RedundancyJudge | None = None,
) -> int:
    given_order_ids: list[str] = []
    redundant = 0
    for turn in transcript.turns:
        found_in_user = _ORDER_ID_TOKEN.findall(turn.user_message)
        already_known = list(given_order_ids)
        if already_known and turn.agent_message and turn.interrupt_prompt is None:
            is_redundant = bool(
                _ASK_ORDER_ID.search(turn.agent_message) and "?" in turn.agent_message
            )
            if not is_redundant and judge is not None:
                is_redundant = judge(turn.user_message, turn.agent_message, already_known)
            if is_redundant:
                redundant += 1
        for oid in found_in_user:
            upper = oid.upper()
            if upper not in given_order_ids:
                given_order_ids.append(upper)
    return redundant


def _fact_retention(
    scenario: Scenario, transcript: ConversationTranscript
) -> tuple[float | None, int]:
    """Return (retention over valid probes, number of valid probes).

    A checkpoint is the turn at which the script asks the agent to recall a fact. The
    simulated user can finish before that turn; such a checkpoint was never asked, so it
    is not reached and is left out instead of counting as a miss. A probe message that
    restates the fact itself is left out too, since repeating it back tests no memory.
    """
    last_turn = max((turn.turn_index for turn in transcript.turns), default=0)
    probes = {turn.turn_index: turn.user_message.lower() for turn in transcript.turns}
    reached = [
        cp
        for cp in scenario.checkpoints
        if cp.turn_hint <= last_turn
        # A probe that restates the fact does not test recall.
        and not any(sub.lower() in probes.get(cp.turn_hint, "") for sub in cp.expected_substrings)
    ]
    if not reached:
        return None, 0
    hits = 0
    for cp in reached:
        candidate_replies = [
            turn.agent_message.lower()
            for turn in transcript.turns
            if turn.turn_index >= cp.turn_hint
        ]
        combined = "\n".join(candidate_replies)
        if all(sub.lower() in combined for sub in cp.expected_substrings):
            hits += 1
    return hits / len(reached), len(reached)


def _handoff_appropriate(scenario: Scenario, transcript: ConversationTranscript) -> bool:
    observed = [turn.handoff_reason for turn in transcript.turns if turn.handoff_reason]
    expects_handoff = scenario.expected_outcome.startswith("handoff:")
    if not expects_handoff:
        return not observed
    target = scenario.expected_outcome.split(":", 1)[1]
    return target in observed


def evaluate_transcript(
    scenario: Scenario,
    transcript: ConversationTranscript,
    *,
    loop_threshold: int = 3,
    redundancy_judge: RedundancyJudge | None = None,
) -> ScenarioEvaluation:
    observed_tools: list[str] = []
    call_counts: Counter[str] = Counter()
    wrong_customer = False
    for turn in transcript.turns:
        for call in turn.tool_calls:
            observed_tools.append(call.name)
            call_counts[_canonical_tool_call(call.name, call.args)] += 1
            if (
                call.customer_id_accessed is not None
                and call.customer_id_accessed != scenario.customer_id
            ):
                wrong_customer = True

    success = _check_outcome(scenario, transcript) and not wrong_customer
    precision, recall = _tool_precision_recall(scenario.expected_tool_calls, observed_tools)
    tokens_by_turn = [turn.input_tokens for turn in transcript.turns]
    retention, reached = _fact_retention(scenario, transcript)
    had_error = transcript.stop_reason == "error" or any(
        turn.error_type is not None for turn in transcript.turns
    )

    return ScenarioEvaluation(
        scenario_id=scenario.id,
        category=scenario.category,
        repeat_index=transcript.repeat_index,
        task_success=success,
        tool_call_precision=precision,
        tool_call_recall=recall,
        wrong_customer_access=wrong_customer,
        turns_to_success=len(transcript.turns) if success else None,
        redundant_questions=_count_redundant_questions(transcript, judge=redundancy_judge),
        fact_retention=retention,
        fact_checkpoints=len(scenario.checkpoints),
        fact_checkpoints_reached=reached,
        loop_detected=any(count >= loop_threshold for count in call_counts.values()),
        handoff_appropriate=_handoff_appropriate(scenario, transcript),
        tokens_by_turn=tokens_by_turn,
        total_input_tokens=sum(tokens_by_turn),
        total_output_tokens=sum(turn.output_tokens for turn in transcript.turns),
        had_error=had_error,
    )


def _mean_ci(values: list[float], *, n_resamples: int, seed: int, alpha: float) -> dict[str, Any]:
    if not values:
        return {"mean": None, "low": None, "high": None, "n": 0}
    ci = bootstrap_ci(values, n_resamples=n_resamples, seed=seed, alpha=alpha)
    return {"mean": ci.point, "low": ci.low, "high": ci.high, "n": len(values)}


def aggregate_evaluations(
    evals: list[ScenarioEvaluation],
    *,
    n_resamples: int = 2000,
    seed: int = 27,
    alpha: float = 0.05,
) -> dict[str, Any]:
    total = len(evals)
    wrong_cust = sum(1 for e in evals if e.wrong_customer_access)
    wrong_ci = wilson_interval(wrong_cust, total, alpha=alpha) if total else None
    wrong_low = wrong_ci.low if wrong_ci is not None else 0.0
    wrong_high = wrong_ci.high if wrong_ci is not None else 0.0

    by_scenario: dict[str, list[float]] = defaultdict(list)
    by_category: dict[str, list[ScenarioEvaluation]] = defaultdict(list)
    tokens_at_turn: dict[int, list[int]] = defaultdict(list)
    for row in evals:
        by_scenario[row.scenario_id].append(1.0 if row.task_success else 0.0)
        by_category[row.category].append(row)
        for idx, tok in enumerate(row.tokens_by_turn, start=1):
            tokens_at_turn[idx].append(tok)

    repeat_stds = [statistics.pstdev(scores) for scores in by_scenario.values() if len(scores) >= 2]

    token_curve = []
    for turn_idx in sorted(tokens_at_turn):
        vals = sorted(tokens_at_turn[turn_idx])
        p95_idx = min(len(vals) - 1, int(0.95 * (len(vals) - 1)))
        token_curve.append(
            {
                "turn": turn_idx,
                "n": len(vals),
                "mean_input_tokens": statistics.mean(vals),
                "p95_input_tokens": vals[p95_idx],
            }
        )

    categories = {}
    for cat, rows in sorted(by_category.items()):
        categories[cat] = {
            "n": len(rows),
            "task_success": sum(r.task_success for r in rows) / len(rows),
            "handoff_appropriate": sum(r.handoff_appropriate for r in rows) / len(rows),
            "redundant_questions_mean": statistics.mean(r.redundant_questions for r in rows),
            "loop_rate": sum(r.loop_detected for r in rows) / len(rows),
        }

    return {
        "n_runs": total,
        "n_scenarios": len(by_scenario),
        "task_success": _mean_ci(
            [1.0 if e.task_success else 0.0 for e in evals],
            n_resamples=n_resamples,
            seed=seed,
            alpha=alpha,
        ),
        "tool_call_precision": _mean_ci(
            [e.tool_call_precision for e in evals if e.tool_call_precision is not None],
            n_resamples=n_resamples,
            seed=seed,
            alpha=alpha,
        ),
        "tool_call_recall": _mean_ci(
            [e.tool_call_recall for e in evals if e.tool_call_recall is not None],
            n_resamples=n_resamples,
            seed=seed,
            alpha=alpha,
        ),
        "wrong_customer_access": {
            "count": wrong_cust,
            "total": total,
            "rate": wrong_cust / total if total else 0.0,
            "wilson_low": wrong_low,
            "wilson_high": wrong_high,
        },
        "turns_to_success": _mean_ci(
            [float(e.turns_to_success) for e in evals if e.turns_to_success is not None],
            n_resamples=n_resamples,
            seed=seed,
            alpha=alpha,
        ),
        "redundant_questions": _mean_ci(
            [float(e.redundant_questions) for e in evals],
            n_resamples=n_resamples,
            seed=seed,
            alpha=alpha,
        ),
        "fact_retention": _mean_ci(
            [e.fact_retention for e in evals if e.fact_retention is not None],
            n_resamples=n_resamples,
            seed=seed,
            alpha=alpha,
        ),
        "fact_checkpoints": {
            "reached": sum(e.fact_checkpoints_reached for e in evals),
            "total": sum(e.fact_checkpoints for e in evals),
        },
        "loop_rate": _mean_ci(
            [1.0 if e.loop_detected else 0.0 for e in evals],
            n_resamples=n_resamples,
            seed=seed,
            alpha=alpha,
        ),
        "handoff_appropriate": _mean_ci(
            [1.0 if e.handoff_appropriate else 0.0 for e in evals],
            n_resamples=n_resamples,
            seed=seed,
            alpha=alpha,
        ),
        "error_rate": sum(e.had_error for e in evals) / total if total else 0.0,
        "repeat_task_success_mean_std": (statistics.mean(repeat_stds) if repeat_stds else None),
        "categories": categories,
        "tokens_per_turn_curve": token_curve,
    }
