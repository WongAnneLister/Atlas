"""Resumable refund and return flow with verified order facts and gated policy evidence."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.types import interrupt

from support_agent.context.budget import ContextOverflow
from support_agent.gate.evidence import evaluate
from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import PROMPTS, HandoffReason, make_handoff
from support_agent.graph.model_data import order_block, order_data, refund_data, source_blocks
from support_agent.graph.refund_decision import (
    DECISION_VERSIONS,
    RefundDecision,
    check_decision,
)
from support_agent.graph.refund_query import policy_query
from support_agent.graph.state import CitationRecord, ConversationState
from support_agent.graph.turn_identity import action_key, current_graph_config, turn_message_id
from support_agent.orders.models import Order, OrderNotFound
from support_agent.reliability.guards import diagnostic_type, is_dependency_failure
from support_agent.reliability.stores import GuardedOrders
from support_agent.retrieval.filters import RetrievalFilters, retrieve_with_filters
from support_agent.retrieval.scope import scope_chunks

logger = logging.getLogger(__name__)
ORDER_ID = re.compile(r"\bORD[- ]?\d{6}\b", re.IGNORECASE)


class RefundPath:
    def __init__(self, deps: GraphDeps) -> None:
        self.deps = deps
        prompt_file, self.decision_schema = DECISION_VERSIONS[deps.settings.refund.decision_version]
        self.prompt = (PROMPTS / prompt_file).read_text(encoding="utf-8")
        self.policy_notice = (
            (PROMPTS / "policy_version_notice.txt").read_text(encoding="utf-8").strip()
        )

    def _service(self) -> GuardedOrders:
        return self.deps.guarded_orders()

    def identify_order(self, state: ConversationState) -> dict[str, Any]:
        service = self._service()
        query = " ".join(
            message.content for message in state.messages if isinstance(message.content, str)
        )
        match = ORDER_ID.search(query)
        order_id = match.group(0).upper().replace(" ", "-") if match else None
        if order_id is None:
            try:
                built = self.deps.context_builder().build(
                    "order_extract",
                    task_prompt=(
                        "Extract an order id from the customer request. Return the id or say none."
                    ),
                    user_text=query,
                )
                response, _ = self.deps.models.invoke("order_extract", "fast", built)
                content = getattr(response, "content", "")
                if isinstance(content, str):
                    model_match = ORDER_ID.search(content)
                    order_id = (
                        model_match.group(0).upper().replace(" ", "-") if model_match else None
                    )
            except Exception as error:
                logger.info("Fast order extraction failed: %s", type(error).__name__)
        if order_id:
            try:
                service.get_order(order_id, state.customer_id or "")
                return {
                    "refund_order_id": order_id,
                    "refund_candidates": [],
                    "trace": [*state.trace, "after_sales", "refund_identify"],
                }
            except (OrderNotFound, ValueError):
                pass
            except Exception as error:
                return self._identify_unavailable(state, error)
        try:
            orders = service.list_recent_orders(state.customer_id or "")
        except (FileNotFoundError, ValueError):
            return {
                **make_handoff(state.model_copy(deep=True), HandoffReason.ORDER_NOT_FOUND),
                "trace": [*state.trace, "after_sales", "refund_identify", "handoff"],
            }
        except Exception as error:
            return self._identify_unavailable(state, error)
        choices = [self._order_choice(order) for order in orders]
        selected = interrupt({"type": "order_picker", "orders": choices})
        if selected == "none" or not isinstance(selected, str):
            return {
                **make_handoff(state.model_copy(deep=True), HandoffReason.ORDER_NOT_FOUND),
                "trace": [*state.trace, "after_sales", "refund_identify", "handoff"],
            }
        selected = selected.upper().replace(" ", "-")
        if selected not in {choice["order_id"] for choice in choices}:
            return {
                **make_handoff(state.model_copy(deep=True), HandoffReason.ORDER_NOT_FOUND),
                "trace": [*state.trace, "refund_identify", "handoff"],
            }
        return {
            "refund_order_id": selected,
            "refund_candidates": choices,
            "trace": [*state.trace, "after_sales", "refund_identify"],
        }

    @classmethod
    def _identify_unavailable(cls, state: ConversationState, error: Exception) -> dict[str, Any]:
        if not is_dependency_failure(error):
            raise error
        current = state.model_copy(
            update={"trace": [*state.trace, "after_sales", "refund_identify"]}
        )
        return cls._handoff(current, HandoffReason.DEPENDENCY_UNAVAILABLE)

    def load_order(self, state: ConversationState) -> dict[str, Any]:
        if not state.refund_order_id or not state.customer_id:
            return self._handoff(state, HandoffReason.ORDER_NOT_FOUND)
        turn_id = turn_message_id(state.messages)
        key = action_key(current_graph_config(), turn_id, "refund_request")
        try:
            service = self._service()
            order = service.get_order(state.refund_order_id, state.customer_id)
            pending = service.pending_refund_item_ids(
                state.refund_order_id,
                state.customer_id,
                idempotency_key=key,
                legacy_turn_id=turn_id,
            )
        except (OrderNotFound, ValueError):
            return self._handoff(state, HandoffReason.ORDER_NOT_FOUND)
        except Exception as error:
            if not is_dependency_failure(error):
                raise
            current = state.model_copy(update={"trace": [*state.trace, "refund_load"]})
            return self._handoff(current, HandoffReason.DEPENDENCY_UNAVAILABLE)
        today = self.deps.settings.orders.today
        days = (today - order.delivered_at).days if order.delivered_at else None
        context = {
            "order": order_data(order),
            "days_since_order": (today - order.order_date).days,
            "days_since_delivery": days,
            "today": today.isoformat(),
        }
        if pending:
            # Only when present, so the decision prompt is unchanged for other orders.
            context["pending_refund_item_ids"] = pending
        return {"order_context": context, "trace": [*state.trace, "refund_load"]}

    def retrieve_policy(self, state: ConversationState) -> dict[str, Any]:
        if state.handoff is not None:
            return {}
        order = self._order_from_state(state)
        if order is None:
            return self._handoff(state, HandoffReason.ORDER_NOT_FOUND)
        settings = self.deps.settings
        query = policy_query(order, state.intent.value if state.intent else None, settings)
        retrieval = settings.retrieval
        filters = RetrievalFilters(as_of=order.order_date) if retrieval.filters.enabled else None
        filters_applied = False
        scope = retrieval.store_scope
        pool = (
            max(retrieval.rerank_top_k, scope.pool_k) if scope.enabled else retrieval.rerank_top_k
        )
        error_type = None
        dependency_unavailable = False
        try:
            ranked, filters_applied = retrieve_with_filters(
                self.deps.knowledge_retriever(), query, pool, filters
            )
            chunks, _, _ = scope_chunks(query, ranked, scope, retrieval.rerank_top_k)
        except Exception as error:
            error_type = diagnostic_type(error)
            dependency_unavailable = is_dependency_failure(error)
            logger.warning("Refund policy retrieval failed: %s", error_type)
            chunks = []
        gate = evaluate(
            query,
            chunks,
            self.deps.settings.gate,
            allow_untuned=self.deps.allow_untuned_gate,
        )
        build_id = self.deps.current_build_id()
        evidence = {
            "retrieval": chunks,
            "gate": gate,
            "retrieval_build_id": build_id,
            "filters": filters,
            "filters_applied": filters_applied,
        }
        if not gate.passed:
            current = state.model_copy(update=evidence, deep=True)
            return {
                **make_handoff(
                    current,
                    HandoffReason.DEPENDENCY_UNAVAILABLE
                    if dependency_unavailable
                    else HandoffReason.LOW_EVIDENCE,
                ),
                "retrieval_error_type": error_type,
                **evidence,
                "refund_policy_query": query,
                "trace": [*state.trace, "refund_retrieve", "handoff"],
            }
        return {
            **evidence,
            "refund_policy_query": query,
            "trace": [*state.trace, "refund_retrieve"],
        }

    def decide(self, state: ConversationState) -> dict[str, Any]:
        order = self._order_from_state(state)
        if order is None or state.gate is None or not state.gate.passed:
            return self._handoff(state, HandoffReason.POLICY_REQUIRES_HUMAN)
        sources = source_blocks(state.retrieval, include_validity=True)
        data = refund_data(state.order_context or {})
        order_facts = order_block(json.dumps(data, sort_keys=True))
        try:
            built = self.deps.context_builder().build(
                "decide",
                task_prompt=self.prompt,
                user_text=f"Order facts:\n{order_facts}\n\nSources:\n{sources}",
                history=state.messages[:-1],
                order_context=data,
                order_context_never_trim=True,
                current_date=self.deps.settings.orders.today,
            )
            response, _ = self.deps.models.structured("decide", "main", self.decision_schema, built)
        except ContextOverflow:
            cb = getattr(self.deps.observer, "context_overflow", None)
            if callable(cb):
                cb("decide")
            return self._handoff(state, HandoffReason.CONTEXT_OVERFLOW)
        except Exception as error:
            logger.warning("Refund decision failed: %s", type(error).__name__)
            reason = (
                HandoffReason.DEPENDENCY_UNAVAILABLE
                if is_dependency_failure(error)
                else HandoffReason.POLICY_REQUIRES_HUMAN
            )
            return self._handoff(state, reason)
        decision = self._check_decision(response.value, order, state)
        return {
            "refund_decision": decision.model_dump(),
            "trace": [*state.trace, "refund_decide"],
        }

    def act(self, state: ConversationState) -> dict[str, Any]:
        if state.handoff is not None:
            return {}
        decision = self._decision(state)
        if decision is None:
            return self._handoff(state, HandoffReason.POLICY_REQUIRES_HUMAN)
        if decision.eligible == "needs_human":
            return self._handoff(state, HandoffReason.POLICY_REQUIRES_HUMAN)
        records = [
            CitationRecord(
                n=number,
                chunk_id=chunk.chunk_id,
                section_id=chunk.section_id,
                heading_path=chunk.heading_path,
            )
            for number, chunk in enumerate(state.retrieval, 1)
            if number in decision.citations
        ]
        citations = " ".join(f"[{record.n}]" for record in records)
        notice = self._historical_policy_notice(state, records)
        if decision.eligible == "no":
            reason = " ".join(decision.reasons) or "The policy does not support this request."
            answer = (
                f"I cannot approve this request. {reason} "
                f"You can ask a human agent to review it. {citations}"
            ).strip()
            answer = f"{notice}{answer}"
            return {
                "answer": answer,
                "citations": records,
                "messages": [AIMessage(content=answer)],
                "trace": [*state.trace, "refund_act"],
            }
        if not state.refund_order_id or not state.customer_id:
            return self._handoff(state, HandoffReason.ORDER_NOT_FOUND)
        turn_id = turn_message_id(state.messages)
        key = action_key(current_graph_config(), turn_id, "refund_request")
        if key is None:
            return self._handoff(state, HandoffReason.POLICY_REQUIRES_HUMAN)
        try:
            request = self._service().create_refund_request(
                state.refund_order_id,
                state.customer_id,
                decision.items,
                "; ".join(decision.reasons) or "Customer refund request",
                idempotency_key=key,
                legacy_turn_id=turn_id,
            )
        except Exception as error:
            logger.warning("Refund request creation failed: %s", diagnostic_type(error))
            reason = (
                HandoffReason.DEPENDENCY_UNAVAILABLE
                if is_dependency_failure(error)
                else HandoffReason.POLICY_REQUIRES_HUMAN
            )
            return self._handoff(state, reason)
        answer = (
            f"{notice}Your refund request {request.request_id} is pending human review. {citations}"
        ).strip()
        return {
            "refund_request": request.model_dump(mode="json"),
            "answer": answer,
            "citations": records,
            "messages": [AIMessage(content=answer)],
            "trace": [*state.trace, "refund_act"],
        }

    def _historical_policy_notice(
        self, state: ConversationState, citations: list[CitationRecord]
    ) -> str:
        order = self._order_from_state(state)
        if order is None:
            return ""
        today = self.deps.settings.orders.today
        for citation in citations:
            chunk = state.retrieval[citation.n - 1]
            start, end = chunk.effective_from, chunk.effective_to
            if start is not None and end is not None and start <= order.order_date < end <= today:
                return (
                    self.policy_notice.format(
                        order_date=order.order_date,
                        effective_from=start,
                        effective_to=end,
                        citation=citation.n,
                    )
                    + " "
                )
        return ""

    @staticmethod
    def _order_choice(order: Order) -> dict[str, Any]:
        return {
            "order_id": order.order_id,
            "order_date": order.order_date.isoformat(),
            "status": order.status.value,
            "total": str(order.total),
            "currency": order.currency,
            "item_names": [item.name for item in order.items],
        }

    @staticmethod
    def _order_from_state(state: ConversationState) -> Order | None:
        if not state.order_context or not isinstance(state.order_context.get("order"), dict):
            return None
        try:
            return Order.model_validate(state.order_context["order"])
        except Exception:
            return None

    @staticmethod
    def _parse_decision(raw: Any) -> RefundDecision:
        if isinstance(raw, dict) and "parsed" in raw:
            raw = raw["parsed"]
        if isinstance(raw, RefundDecision):
            return raw
        if isinstance(raw, dict):
            return RefundDecision.model_validate(raw)
        content = getattr(raw, "content", None)
        if isinstance(content, str):
            return RefundDecision.model_validate_json(content)
        raise ValueError("Refund model returned no structured decision")

    @staticmethod
    def _decision(state: ConversationState) -> RefundDecision | None:
        if state.refund_decision is None:
            return None
        try:
            return RefundDecision.model_validate(state.refund_decision)
        except Exception:
            return None

    @staticmethod
    def _check_decision(
        decision: RefundDecision, order: Order, state: ConversationState
    ) -> RefundDecision:
        return check_decision(decision, order, state)

    @staticmethod
    def _handoff(state: ConversationState, reason: HandoffReason) -> dict[str, Any]:
        current = state.model_copy(deep=True)
        current.trace.append("handoff")
        return {**make_handoff(current, reason), "trace": current.trace}
