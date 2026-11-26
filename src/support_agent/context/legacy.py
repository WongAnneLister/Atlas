"""Message layout from before the ContextBuilder, used when `context.enabled` is false.

Every node sent its own task prompt as the only system message, then its input. No shared
preamble, date, pinned facts, profile, summaries or token budget were added. The query
rewrite alone sent its recent turns instead of a single input message. Keeping this layout
behind the switch lets the ContextBuilder be measured against the prompts the evidence
gate and claim checks were calibrated on.
"""

from __future__ import annotations

from collections.abc import Sequence

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage


def legacy_messages(
    task_prompt: str,
    user_text: str,
    *,
    turns: Sequence[BaseMessage] | None = None,
    extra: Sequence[BaseMessage] = (),
) -> list[BaseMessage]:
    """Return `[system prompt, input..., extra...]` exactly as the nodes built it before."""
    body: list[BaseMessage] = list(turns) if turns is not None else []
    if turns is None and user_text:
        body = [HumanMessage(content=user_text)]
    return [SystemMessage(content=task_prompt), *body, *extra]
