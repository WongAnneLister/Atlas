"""Publish only final replies that pass the output checks."""

import json
from contextlib import suppress
from typing import Any

from langchain_core.messages import AIMessage

from support_agent.cache.eligibility import answer_cache_write_eligibility
from support_agent.cache.layers import CachedAnswer
from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import (
    PROMPTS,
    HandoffPayload,
    HandoffReason,
    make_handoff,
    mark_parts_handed_off,
)
from support_agent.graph.state import ConversationState
from support_agent.graph.turn_identity import current_graph_config
from support_agent.guardrails.output import OutputChecks, OutputFlag
from support_agent.guardrails.pii import find_pii
from support_agent.memory.long_term.policy import apply_write_policy, extract_memory_candidates


def _evidence(state: ConversationState) -> list[str]:
    """Cited policy text and the customer-scoped order data of this turn."""
    chunks = {chunk.chunk_id: chunk.text for chunk in state.retrieval}
    texts = [chunks.get(record.chunk_id, "") for record in state.citations]
    if state.order_context:
        texts.append(json.dumps(state.order_context, default=str))
    return texts


class OutputGuard:
    def __init__(self, deps: GraphDeps) -> None:
        self.deps = deps
        self.settings = deps.settings.guardrails.output
        excluded = (
            () if deps.settings.grounding.enabled else ("verify_claims.md", "split_claims.md")
        )
        self.checks = OutputChecks(self.settings, PROMPTS, exclude_prompts=excluded)

    def _violation(self, state: ConversationState) -> OutputFlag | None:
        if self.settings.prompt_leak and self.checks.prompt_leaked(state.answer):
            return "prompt_leak"
        if self.settings.foreign_pii:
            allowed_email = None
            if state.customer_id and any(match.kind == "email" for match in find_pii(state.answer)):
                # Unavailable ownership evidence cannot authorize disclosure.
                with suppress(Exception):
                    allowed_email = self.deps.guarded_orders().customer_email(state.customer_id)
            if self.checks.foreign_pii(state.answer, allowed_email, _evidence(state)):
                return "foreign_pii"
        if self.settings.commitments and self.checks.unbacked_commitment(state):
            return "unbacked_commitment"
        return None

    def __call__(self, state: ConversationState) -> dict[str, Any]:
        trace = [*state.trace, "output_guard"]
        violation = self._violation(state)
        if violation is None:
            self._maybe_cache_answer(state)
            self._maybe_extract_memories_on_handoff(state)
            handoff_update = self._maybe_enqueue_handoff(state, state.handoff)
            return {
                "answer": state.answer,
                "messages": [AIMessage(content=state.answer)] if state.answer else [],
                "handoff": state.handoff,
                "citations": [citation.model_dump() for citation in state.citations],
                **handoff_update,
                "trace": trace,
            }
        original = state.messages
        unsafe = original[-1] if original and isinstance(original[-1], AIMessage) else None
        messages = original[:-1] if unsafe is not None else original
        flags = [*state.guardrail_flags, violation]
        current = state.model_copy(update={"messages": messages, "guardrail_flags": flags})
        parts_update: dict[str, Any] = {}
        if state.route_source == "parts":
            current.parts = mark_parts_handed_off(state.parts, HandoffReason.GUARDRAIL_BLOCKED)
            current.coverage = None
            parts_update = {"parts": current.parts, "coverage": None}
        update = make_handoff(current, HandoffReason.GUARDRAIL_BLOCKED)
        if unsafe is not None:
            update["messages"][0] = update["messages"][0].model_copy(update={"id": unsafe.id})
        handoff_update = self._maybe_enqueue_handoff(current, update.get("handoff"))
        return {
            **update,
            **parts_update,
            **handoff_update,
            "citations": [],
            "guardrail_flags": flags,
            "output_guard_flag": violation,
            "answer_status": "guardrail_blocked",
            "trace": trace,
        }

    def _maybe_cache_answer(self, state: ConversationState) -> None:
        if state.answer_cache_hit is not None:
            return
        eligible, _ = answer_cache_write_eligibility(
            state,
            self.deps.settings.cache,
            grounding_enabled=self.deps.settings.grounding.enabled,
        )
        if not eligible or state.gate is None or not state.retrieval_build_id:
            return
        entry = CachedAnswer(
            answer=state.answer,
            citations=list(state.citations),
            retrieval=list(state.retrieval),
            gate=state.gate,
            coverage=state.coverage,
            claims=list(state.claims) if state.claims is not None else None,
            claims_removed=state.claims_removed,
            filters_applied=state.filters_applied,
            retrieval_build_id=state.retrieval_build_id,
            models=dict(state.answered_by_model),
        )
        self.deps.answer_cache().set(
            query=state.rewritten_query,
            filters=state.filters,
            build_id=state.retrieval_build_id,
            prompt_version=self.deps.prompt_version(),
            models=self.deps.answer_cache_models(),
            entry=entry,
        )

    def _maybe_extract_memories_on_handoff(self, state: ConversationState) -> None:
        lt_cfg = self.deps.settings.memory.long_term
        if (
            not lt_cfg.enabled
            or not lt_cfg.extract_on_handoff
            or state.handoff is None
            or not state.customer_id
        ):
            return
        store = self.deps.long_term_memory()
        if store is None:
            return
        with suppress(Exception):
            candidates = extract_memory_candidates(
                pinned_facts=state.pinned_facts,
                compacted_blocks=state.compacted_blocks,
                messages=state.messages,
                models=self.deps.models,
                builder=self.deps.context_builder(),
                settings=lt_cfg,
            )
            if candidates:
                conv_id = state.handoff.trace_id or "handoff"
                apply_write_policy(
                    store,
                    state.customer_id,
                    candidates,
                    conversation_id=conv_id,
                    settings=lt_cfg,
                )

    def _maybe_enqueue_handoff(
        self, state: ConversationState, payload: HandoffPayload | None
    ) -> dict[str, Any]:
        if payload is None:
            return {}
        queue = self.deps.handoff_queue()
        if queue is None:
            return {}
        cfg = self.deps.settings.handoff
        thread_id = str(current_graph_config().get("configurable", {}).get("thread_id") or "")
        customer_id = state.customer_id or "anonymous"
        conv_id = thread_id.split(":", 1)[1] if ":" in thread_id else (thread_id or "unknown")
        with suppress(Exception):
            item = queue.enqueue(
                conversation_id=conv_id,
                customer_id=customer_id,
                reason=str(payload.reason),
                priority=cfg.priority_for(str(payload.reason)),
                payload=payload.model_dump(mode="json"),
                idempotency_key=payload.idempotency_key,
            )
            if cfg.human_mode_enabled:
                return {"human_mode": True, "active_handoff_id": item.id}
            return {"active_handoff_id": item.id}
        return {}
