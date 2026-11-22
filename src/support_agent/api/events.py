"""Translate graph updates into public chat events."""

import re
from typing import Any

from pydantic import BaseModel

from support_agent.graph.state import CitationRecord

_WORD = re.compile(r"\S+\s*")


class SseEvent(BaseModel):
    name: str
    data: Any


def events_for_update(node_name: str, update: dict[str, Any], chunk_words: int) -> list[SseEvent]:
    if node_name == "classify":
        return [
            SseEvent(
                name="meta",
                data={
                    "intent": update["intent"],
                    "path": update["path"],
                    "confidence": update["intent_confidence"],
                    "low_confidence": update["intent_low_confidence"],
                },
            )
        ]
    if node_name == "__interrupt__":
        return [SseEvent(name="interrupt", data=update)]
    if node_name != "output_guard" or not (answer := update.get("answer")):
        return []
    handoff_events = []
    if handoff := update.get("handoff"):
        message = handoff.customer_message
        data = {"reason": handoff.reason, "message": message or answer}
        if handoff.trace_id:
            data["trace_id"] = handoff.trace_id
        handoff_events.append(SseEvent(name="handoff", data=data))
        if message is None:
            return handoff_events
        answer = answer.removesuffix(f"\n\n{message}")

    events = []
    start = 0
    for count, word in enumerate(_WORD.finditer(answer), 1):
        if count % chunk_words == 0:
            events.append(SseEvent(name="token", data={"text": answer[start : word.end()]}))
            start = word.end()
    if start < len(answer):
        events.append(SseEvent(name="token", data={"text": answer[start:]}))
    citations = [
        CitationRecord.model_validate(item).model_dump(mode="json")
        for item in update.get("citations", [])
    ]
    return [*events, SseEvent(name="citations", data=citations), *handoff_events]
