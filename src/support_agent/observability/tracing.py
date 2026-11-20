"""Optional Langfuse tracing for one conversation turn.

Tracing runs only when `tracing.enabled` is true and both Langfuse keys are set.
Otherwise nothing here imports `langfuse`, and every call is a no-op.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from support_agent.config import Settings, TracingSettings

logger = logging.getLogger(__name__)
REDACTED = "[redacted]"
_KEY_VARS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
# State fields that hold customer text (or a rewrite of it).
_CUSTOMER_TEXT_KEYS = frozenset({"rewritten_query"})
_CUSTOMER_ROLES = frozenset({"human", "user"})
_TRIMMED_CHUNK_KEYS = {"chunk_id", "section_id", "scores"}
_LANGFUSE: Any = None


def tracing_configured(settings: TracingSettings) -> bool:
    return settings.enabled and all(os.environ.get(name, "").strip() for name in _KEY_VARS)


def _is_chunk(value: Mapping[str, Any]) -> bool:
    return "chunk_id" in value and "text" in value


def _trim_chunk(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": value.get("chunk_id"),
        "section_id": value.get("section_id"),
        "scores": value.get("scores"),
    }


def mask_data(data: Any, *, settings: TracingSettings) -> Any:
    """Keep chunk ids and scores, never chunk text; optionally drop customer text."""
    if isinstance(data, BaseMessage):
        data = {"type": data.type, "content": data.content}
    elif isinstance(data, BaseModel):
        data = data.model_dump(mode="json")
    if isinstance(data, Mapping):
        if _is_chunk(data):
            return _trim_chunk(data)
        customer = data.get("type") in _CUSTOMER_ROLES or data.get("role") in _CUSTOMER_ROLES
        masked: dict[str, Any] = {}
        for key, value in data.items():
            if settings.redact_inputs and (
                key in _CUSTOMER_TEXT_KEYS or (customer and key == "content")
            ):
                masked[key] = REDACTED
            else:
                masked[key] = mask_data(value, settings=settings)
        return masked
    if isinstance(data, list | tuple):
        items = [mask_data(value, settings=settings) for value in data]
        chunks = all(
            isinstance(value, Mapping) and set(value) == _TRIMMED_CHUNK_KEYS for value in items
        )
        return items[: settings.max_chunks] if items and chunks else items
    return data


def _value(item: Any) -> Any:
    return getattr(item, "value", item)


def turn_tags(values: Mapping[str, Any]) -> tuple[list[str], dict[str, str]]:
    """Low-cardinality trace tags plus the gate score as metadata."""
    tags: list[str] = []
    metadata: dict[str, str] = {}
    if values.get("intent") is not None:
        tags.append(f"intent:{_value(values['intent'])}")
    if values.get("path") is not None:
        tags.append(f"path:{_value(values['path'])}")
    gate = values.get("gate")
    if isinstance(gate, BaseModel):
        gate = gate.model_dump()
    if isinstance(gate, Mapping):
        tags.append(f"gate_passed:{str(bool(gate.get('passed'))).lower()}")
        if isinstance(gate.get("score"), int | float):
            metadata["gate_score"] = f"{float(gate['score']):.4f}"
    handoff = values.get("handoff")
    reason = getattr(handoff, "reason", None)
    if reason is None and isinstance(handoff, Mapping):
        reason = handoff.get("reason")
    if reason is not None:
        tags.append(f"handoff:{_value(reason)}")
    return tags, metadata


class TurnTrace:
    """One traced turn. Disabled tracing gives empty callbacks and no-op methods."""

    def __init__(self) -> None:
        self.callbacks: list[BaseCallbackHandler] = []
        self.config_metadata: dict[str, str] = {}
        self._root: Any = None
        self._session_id = ""
        self._user_id = ""
        self._name = ""

    def finish(self, values: Mapping[str, Any] | None, *, error_type: str | None = None) -> None:
        if self._root is None:
            return
        try:
            tags, metadata = turn_tags(values or {})
            if error_type:
                tags.append("error")
                metadata["error_type"] = error_type
            self._set_attributes(tags=tags, metadata=metadata)
            answer = (values or {}).get("answer")
            self._root.update(
                output={"answer": answer} if answer else None,
                metadata=metadata or None,
                level="ERROR" if error_type else None,
            )
            self._root.end()
        except Exception as error:
            logger.warning("Trace finish failed: %s", type(error).__name__)
        finally:
            self._root = None

    def _set_attributes(
        self, tags: list[str] | None = None, metadata: dict[str, Any] | None = None
    ) -> None:
        from langfuse import propagate_attributes
        from opentelemetry import trace as otel_trace

        # The root span is made current only inside this synchronous block, so the
        # turn may run across worker threads without carrying an OTel context.
        with (
            otel_trace.use_span(self._root._otel_span, end_on_exit=False),
            propagate_attributes(
                session_id=self._session_id,
                user_id=self._user_id,
                trace_name=self._name,
                tags=tags,
                metadata=metadata,
            ),
        ):
            pass


def _client(settings: TracingSettings) -> Any:
    global _LANGFUSE
    if _LANGFUSE is None:
        from langfuse import Langfuse

        def mask(*, data: Any, **_: Any) -> Any:
            return mask_data(data, settings=settings)

        # The callback handler finds this client by public key (langfuse.get_client).
        _LANGFUSE = Langfuse(mask=mask)
    return _LANGFUSE


def start_turn(
    settings: Settings,
    *,
    name: str,
    conversation_id: str,
    customer_id: str,
    input_text: str | None,
    trace_id: str | None = None,
) -> TurnTrace:
    """Open a root span for one turn; graph spans hang under it via the callback."""
    turn = TurnTrace()
    if not tracing_configured(settings.tracing):
        return turn
    try:
        from langfuse.langchain import CallbackHandler

        client = _client(settings.tracing)
        text = REDACTED if settings.tracing.redact_inputs and input_text else input_text
        root = client.start_observation(
            name=name,
            as_type="span",
            input={"message": text} if text is not None else None,
            trace_context={"trace_id": trace_id} if trace_id is not None else None,
        )
        turn._root = root
        turn._session_id, turn._user_id, turn._name = conversation_id, customer_id, name
        turn._set_attributes()
        turn.callbacks = [
            CallbackHandler(trace_context={"trace_id": root.trace_id, "parent_span_id": root.id})
        ]
        turn.config_metadata = {
            "langfuse_session_id": conversation_id,
            "langfuse_user_id": customer_id,
        }
    except Exception as error:
        logger.warning("Tracing disabled for this turn: %s", type(error).__name__)
        return TurnTrace()
    return turn


def flush() -> None:
    if _LANGFUSE is None:
        return
    try:
        _LANGFUSE.flush()
    except Exception as error:
        logger.warning("Trace flush failed: %s", type(error).__name__)
