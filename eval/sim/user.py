"""Role-playing customer simulator isolated from all internal agent state."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from eval.sim.models import Scenario
from support_agent.config import REPO_ROOT, Settings
from support_agent.llm import get_chat_model

PROMPT_PATH = REPO_ROOT / "eval" / "prompts" / "user_sim.md"
DONE_TOKEN = "[DONE]"


@dataclass(frozen=True)
class SimReply:
    text: str
    done: bool


def build_simulator_model(settings: Settings) -> tuple[BaseChatModel, str]:
    """Build a simulator chat model with its own temperature and optional model override."""
    sim = settings.eval.sim
    override = os.getenv("SIM_MODEL") or sim.model
    model_kwargs = dict(settings.llm.model_kwargs)
    if sim.seed is not None:
        model_kwargs.setdefault("seed", sim.seed)
    sim_settings = settings.model_copy(deep=True)
    sim_settings.llm.temperature = sim.temperature
    sim_settings.llm.model_kwargs = model_kwargs
    model = get_chat_model(sim.model_role, sim_settings, model_name=override)
    label = override or getattr(sim_settings.llm, f"{sim.model_role}_model") or sim.model_role
    return model, str(label)


def _scenario_brief(scenario: Scenario, turn_index: int) -> str:
    payload = {
        "turn_index": turn_index,
        "max_turns": scenario.max_turns,
        "persona": scenario.persona.model_dump(),
        "goal": scenario.goal,
        "facts": scenario.facts,
        "hidden_info": scenario.hidden_info,
        "script_hints": scenario.script_hints,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _parse_done(raw: str) -> SimReply:
    stripped = raw.strip()
    done = DONE_TOKEN in stripped
    cleaned = stripped.replace(DONE_TOKEN, "").strip()
    return SimReply(text=cleaned, done=done)


class UserSimulator:
    """Drives the customer side using ONLY visible conversation messages."""

    def __init__(
        self,
        model: BaseChatModel,
        *,
        model_name: str = "injected",
        prompt: str | None = None,
    ) -> None:
        self.model = model
        self.model_name = model_name
        self.prompt = prompt if prompt is not None else PROMPT_PATH.read_text(encoding="utf-8")

    def next_turn(
        self,
        scenario: Scenario,
        visible_history: list[tuple[Literal["user", "assistant"], str]],
        turn_index: int,
    ) -> SimReply:
        """Generate the customer's next utterance from visible messages alone."""
        messages: list[BaseMessage] = [
            SystemMessage(
                content=f"{self.prompt}\n\nScenario:\n{_scenario_brief(scenario, turn_index)}"
            )
        ]
        if not visible_history:
            messages.append(
                HumanMessage(content="Start the conversation with your first message to support.")
            )
        else:
            # Flip perspective: agent messages are HumanMessage inputs to the customer simulator;
            # prior customer messages are AIMessage outputs of the simulator.
            for role, content in visible_history:
                if role == "user":
                    messages.append(AIMessage(content=content))
                else:
                    messages.append(HumanMessage(content=content))
        response = self.model.invoke(messages)
        content = response.content if isinstance(response.content, str) else str(response.content)
        return _parse_done(content)

    def choose_order(self, scenario: Scenario, candidates: list[dict[str, Any]]) -> str:
        """Select an order from visible picker candidates during a refund interrupt."""
        target = scenario.facts.get("order_id") or scenario.hidden_info.get("order_id")
        candidate_ids = [
            str(item.get("order_id", ""))
            for item in candidates
            if isinstance(item, dict) and item.get("order_id")
        ]
        if isinstance(target, str) and target in candidate_ids:
            return target
        if not candidate_ids:
            return "none"
        prompt = (
            "The support agent asked you to pick one order from the list below. "
            "Reply with ONLY the exact order_id that matches your scenario facts, or 'none'.\n"
            f"Facts: {json.dumps(scenario.facts, ensure_ascii=False)}\n"
            f"Hidden info: {json.dumps(scenario.hidden_info, ensure_ascii=False)}\n"
            f"Candidates: {json.dumps(candidates, ensure_ascii=False)}"
        )
        response = self.model.invoke(
            [SystemMessage(content=self.prompt), HumanMessage(content=prompt)]
        )
        text = (
            response.content if isinstance(response.content, str) else str(response.content)
        ).strip()
        for cid in candidate_ids:
            if cid in text:
                return cid
        return "none"
