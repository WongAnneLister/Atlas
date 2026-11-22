"""Apply input checks before any rewrite or classification call."""

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from support_agent.config import REPO_ROOT
from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import PROMPTS, HandoffReason, make_handoff
from support_agent.graph.nodes.rewrite import reset_turn
from support_agent.graph.state import ConversationState
from support_agent.guardrails.input import InputPatterns


class _Suspicion(BaseModel):
    suspicious: bool


class InputGuard:
    def __init__(self, deps: GraphDeps) -> None:
        self.deps = deps
        self.settings = deps.settings.guardrails.input
        self.patterns = InputPatterns(REPO_ROOT / self.settings.patterns_file)
        self.prompt = (PROMPTS / "input_guard.md").read_text(encoding="utf-8")

    def __call__(self, state: ConversationState) -> dict[str, Any]:
        current = state.messages[-1] if state.messages else None
        if not isinstance(current, HumanMessage) or not isinstance(current.content, str):
            raise ValueError("A current human text message is required")
        decision = self.patterns.check(current.content, self.deps.settings.api.max_message_chars)
        if self.settings.classifier.enabled and decision.action != "block":
            try:
                result, _ = self.deps.models.structured(
                    "input_guard",
                    self.settings.classifier.model_role,
                    _Suspicion,
                    [SystemMessage(content=self.prompt), current],
                )
            except Exception:
                decision.flags.append("input_classifier_error")
            else:
                if result.value.suspicious:
                    decision.flags.append("input_classifier")
        if decision.flags and decision.action == "allow":
            decision.action = "allow_flagged"
        update = {
            **reset_turn(),
            "input_guard_action": decision.action,
            "guardrail_flags": list(decision.flags),
            "trace": [*state.trace, "input_guard"],
        }
        if decision.action != "block":
            return update
        # Keep the original in the private handoff, but exclude it from future model history.
        blocked = state.model_copy(update={**update, "part_retrievals": []})
        reply = make_handoff(blocked, HandoffReason.GUARDRAIL_BLOCKED)
        redacted = current.model_copy(update={"content": "[blocked message]"})
        reply["messages"] = [redacted, *reply["messages"]]
        return {**update, **reply}
