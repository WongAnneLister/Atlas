"""Publish only final replies that pass the output checks."""

import json
import logging
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
from support_agent.observability.online_checks import check_citation_validity

logger = logging.getLogger(__name__)


def _trace_id() -> str | None:
    trace_id = current_graph_config().get("metadata", {}).get("trace_id")
    return trace_id if isinstance(trace_id, str) else None


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
            self._maybe_record_online_event(state, state.handoff)
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
        try:
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
        except Exception as error:  # memory is optional; the handoff itself must still go out
            logger.warning(
                "Long-term memory extraction on handoff failed: %s (trace_id=%s)",
                type(error).__name__,
                _trace_id(),
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
        try:
            item = queue.enqueue(
                conversation_id=conv_id,
                customer_id=customer_id,
                reason=str(payload.reason),
                priority=cfg.priority_for(str(payload.reason)),
                payload=payload.model_dump(mode="json"),
                idempotency_key=payload.idempotency_key,
            )
        except Exception as error:
            # The customer was told a person will follow up; make the failure visible.
            logger.error(
                "Handoff enqueue failed: %s (reason=%s, trace_id=%s)",
                type(error).__name__,
                payload.reason,
                payload.trace_id or _trace_id(),
            )
            return {"handoff_delivery_failed": True}
        if cfg.human_mode_enabled:
            return {"human_mode": True, "active_handoff_id": item.id}
        return {"active_handoff_id": item.id}

    def _maybe_record_online_event(
        self, state: ConversationState, payload: HandoffPayload | None
    ) -> None:
        citation_valid = check_citation_validity(state.answer, state.citations)
        if citation_valid is not None:
            cb = getattr(self.deps.observer, "citation_check", None)
            if callable(cb):
                cb(citation_valid)
        store = self.deps.online_eval()
        if store is None:
            return
        try:
            cfg = current_graph_config()
            thread_id = str(cfg.get("configurable", {}).get("thread_id") or "")
            conv_id = thread_id.split(":", 1)[1] if ":" in thread_id else (thread_id or "unknown")
            trace_id = cfg.get("metadata", {}).get("trace_id")
            tokens = sum(c.input_tokens + c.output_tokens for c in state.context_calls)
            rewrite_skipped = "rewrite" not in state.trace or (
                not any(c.node == "rewrite" for c in state.context_calls)
            )
            store.record_turn_event(
                conversation_id=conv_id,
                customer_id=state.customer_id or "anonymous",
                trace_id=trace_id if isinstance(trace_id, str) else None,
                intent=str(state.intent) if state.intent is not None else None,
                path=str(state.path) if state.path is not None else None,
                gate_score=state.gate.score if state.gate is not None else None,
                gate_passed=state.gate.passed if state.gate is not None else None,
                handoff_reason=str(payload.reason) if payload is not None else None,
                rewrite_skipped=rewrite_skipped,
                tokens_total=tokens,
                cost_usd=0.0,
                citation_valid=citation_valid,
                claims_removed=state.claims_removed,
                guardrail_flags=list(state.guardrail_flags),
                question_text=state.rewritten_query,
                answer_text=state.answer,
            )
        except Exception as error:  # online checks are non-blocking by design
            logger.warning(
                "Online eval event not recorded: %s (trace_id=%s)",
                type(error).__name__,
                _trace_id(),
            )
