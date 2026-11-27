"""Replay the customer messages of a saved simulator chat against the current agent.

A simulated customer never says the same thing twice, so a rare agent failure is hard
to see again. Replay sends the exact recorded customer messages, turn by turn, up to a
chosen probe turn, and records what the agent does on that turn. Each arm is a set of
config overrides on the same code, so a switch can be compared on and off. The agent
runs for real; only the customer side is fixed.

Example:
  python -m eval.sim.replay --run eval/runs/sim-dev-X --probe sim-036-topic_switch:5 \
      --arm on --arm off:agent.order_relookup=false --repeats 5
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from eval.e2e_eval import _model_names
from eval.e2e_speed import run_config_hash
from eval.run_record import git, is_dirty
from eval.sim.build_scenarios import load_scenarios
from eval.sim.models import ConversationTranscript, Scenario, SimTurn
from eval.sim.run import run_suite
from eval.sim.user import SimReply, UserSimulator
from eval.stats import wilson_interval
from support_agent.config import REPO_ROOT, Settings, get_settings
from support_agent.data.doc_models import write_text
from support_agent.graph.deps import GraphDeps
from support_agent.orders.service import OrderService

SCENARIOS = REPO_ROOT / "eval/sets/scenarios_v1.jsonl"


class ReplayCustomer(UserSimulator):
    """Sends recorded customer messages in order; it never calls a model."""

    def __init__(self, transcript: ConversationTranscript) -> None:
        self.model_name = f"replay:{transcript.scenario_id}"
        self.turns = {turn.turn_index: turn for turn in transcript.turns}

    def next_turn(
        self,
        scenario: Scenario,
        visible_history: list[tuple[Literal["user", "assistant"], str]],
        turn_index: int,
        **_: Any,
    ) -> SimReply:
        turn = self.turns.get(turn_index)
        return SimReply(text=turn.user_message if turn else "", done=turn is None)

    def choose_order(self, scenario: Scenario, candidates: list[dict[str, Any]]) -> str:
        turn = next((t for t in self.turns.values() if t.resume_choice), None)
        return turn.resume_choice if turn and turn.resume_choice else "none"


@dataclass(frozen=True)
class Probe:
    scenario_id: str
    turn: int


@dataclass(frozen=True)
class Arm:
    name: str
    overrides: dict[str, Any]


def parse_probe(text: str) -> Probe:
    scenario_id, _, turn = text.rpartition(":")
    return Probe(scenario_id, int(turn))


def parse_arm(text: str) -> Arm:
    """`name` or `name:dotted.key=value,other.key=value` with JSON-style values."""
    name, _, spec = text.partition(":")
    overrides: dict[str, Any] = {}
    for pair in filter(None, spec.split(",")):
        key, _, raw = pair.partition("=")
        try:
            overrides[key] = json.loads(raw)
        except json.JSONDecodeError:
            overrides[key] = raw
    return Arm(name, overrides)


def apply_overrides(settings: Settings, overrides: dict[str, Any]) -> Settings:
    data = settings.model_dump(mode="json")
    for key, value in overrides.items():
        node = data
        *parents, leaf = key.split(".")
        for part in parents:
            node = node[part]
        if leaf not in node:
            raise KeyError(f"Unknown setting: {key}")
        node[leaf] = value
    return Settings.model_validate(data)


def probe_turn_route(turn: SimTurn) -> list[str]:
    """The route recorded for one turn: the thread trace after its last input guard."""
    route = list(turn.route)
    starts = [i for i, step in enumerate(route) if step == "input_guard"]
    return route[starts[-1] :] if starts else route


def outcome(scenario: Scenario, transcript: ConversationTranscript, probe: Probe) -> dict[str, Any]:
    turn = next((t for t in transcript.turns if t.turn_index == probe.turn), None)
    wanted = [
        sub
        for cp in scenario.checkpoints
        if cp.turn_hint == probe.turn
        for sub in cp.expected_substrings
    ]
    if turn is None:
        return {"reached": False, "handoff": None, "recalled": False, "relookup": False}
    return {
        "reached": True,
        "handoff": turn.handoff_reason,
        "recalled": bool(wanted) and all(s.lower() in turn.agent_message.lower() for s in wanted),
        "relookup": "relookup_reminder" in probe_turn_route(turn),
    }


@lru_cache(maxsize=1)
def _dirty_at_start() -> bool:
    return is_dirty()


def _rate(count: int, n: int) -> str:
    if n == 0:
        return "—"
    ci = wilson_interval(count, n, get_settings().eval.stats.alpha)
    return f"{count}/{n} [{ci.low:.0%}, {ci.high:.0%}]"


def render(source: Path, rows: list[dict[str, Any]], provenance: dict[str, Any]) -> str:
    digest = hashlib.sha256((source / "items.jsonl").read_bytes()).hexdigest()[:12]
    lines = [
        "# Replay of saved simulator chats",
        "",
        "Generated by `make eval-sim-replay`. Do not edit by hand.",
        "",
        f"- Git SHA: `{provenance['git_sha']}` (dirty: {provenance['dirty']})",
        f"- Models: {', '.join(f'{k}=`{v}`' for k, v in provenance['models'].items())}",
        f"- Source run: `{source.name}` (items sha256 `{digest}`)",
        f"- Date (UTC): {provenance['date'][:10]}",
        "",
        "The recorded customer messages are sent unchanged up to the probe turn; the agent",
        "runs for real. Each arm overrides config on the same code.",
        "",
        "| Probe | Arm | Overrides | Repeats | tool_error handoff | Recalled the fact "
        "| Re-read reminder fired |",
        "|---|---|---|---:|---|---|---|",
    ]
    for row in rows:
        n = row["n"]
        lines.append(
            f"| `{row['probe']}` | {row['arm']} | `{json.dumps(row['overrides'])}` | {n} | "
            f"{_rate(row['tool_error'], n)} | {_rate(row['recalled'], n)} | "
            f"{_rate(row['relookup'], n)} |"
        )
    return "\n".join(lines) + "\n"


def run(
    source: Path, probes: list[Probe], arms: list[Arm], repeats: int, run_root: Path
) -> tuple[list[dict[str, Any]], dict[str, Any], Path]:
    scenarios = {s.id: s for s in load_scenarios(SCENARIOS)}
    lines = (source / "items.jsonl").read_text(encoding="utf-8").splitlines()
    recorded = {
        t.scenario_id: t
        for t in (ConversationTranscript.model_validate_json(line) for line in lines if line)
    }
    base = get_settings().model_copy(deep=True)
    base.api.rate_limit.per_customer = 10000
    base.api.rate_limit.per_ip = 10000
    provenance = {
        "git_sha": git("rev-parse", "HEAD"),
        "dirty": _dirty_at_start(),
        "config_hash": run_config_hash(base),
        "models": _model_names(base),
        "source_run": source.name,
        "date": datetime.now(UTC).isoformat(),
    }
    rows: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    for probe in probes:
        scenario = scenarios[probe.scenario_id]
        # Stop the chat at the probe turn; the recorded messages drive every turn.
        replayed = scenario.model_copy(update={"max_turns": probe.turn})
        for arm in arms:
            settings = apply_overrides(base, arm.overrides)
            order_service = OrderService(platform=settings)
            graph_deps = GraphDeps(settings=settings, order_service=order_service)
            try:
                transcripts = asyncio.run(
                    run_suite(
                        settings,
                        [replayed],
                        simulator=ReplayCustomer(recorded[probe.scenario_id]),
                        graph_deps=graph_deps,
                        order_service=order_service,
                        repeats=repeats,
                    )
                )
            finally:
                order_service.close()
                graph_deps.close()
            outcomes = [outcome(scenario, t, probe) for t in transcripts]
            rows.append(
                {
                    "probe": f"{probe.scenario_id}:{probe.turn}",
                    "arm": arm.name,
                    "overrides": arm.overrides,
                    "n": len(outcomes),
                    "tool_error": sum(o["handoff"] == "tool_error" for o in outcomes),
                    "recalled": sum(o["recalled"] for o in outcomes),
                    "relookup": sum(o["relookup"] for o in outcomes),
                }
            )
            items.extend(
                {
                    "probe": rows[-1]["probe"],
                    "arm": arm.name,
                    "transcript": t.model_dump(mode="json"),
                }
                for t in transcripts
            )
    run_dir = run_root / f"sim-replay-{datetime.now(UTC):%Y%m%d}-{uuid4().hex[:8]}"
    run_dir.mkdir(parents=True, exist_ok=True)
    write_text(run_dir / "items.jsonl", "".join(json.dumps(i) + "\n" for i in items))
    write_text(run_dir / "run.json", json.dumps({**provenance, "rows": rows}, indent=2) + "\n")
    return rows, provenance, run_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True, help="saved sim run directory")
    parser.add_argument("--probe", action="append", required=True, metavar="SCENARIO:TURN")
    parser.add_argument("--arm", action="append", required=True, metavar="NAME[:k=v,...]")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    args = parser.parse_args(argv)
    _dirty_at_start()
    rows, provenance, run_dir = run(
        args.run,
        [parse_probe(p) for p in args.probe],
        [parse_arm(a) for a in args.arm],
        args.repeats,
        args.run_root,
    )
    write_text(args.report, render(args.run, rows, provenance))
    sys.stdout.write(f"Run record: {run_dir}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
