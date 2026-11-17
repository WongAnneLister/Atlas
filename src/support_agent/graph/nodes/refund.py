"""Resumable refund and return flow with verified order facts and gated policy evidence."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from support_agent.gate.evidence import evaluate
from support_agent.graph.deps import GraphDeps
from support_agent.graph.handoff import PROMPTS, HandoffReason, make_handoff
from support_agent.graph.refund_query import policy_query
from support_agent.graph.state import CitationRecord, ConversationState
from support_agent.orders.models import Order, OrderNotFound
from support_agent.orders.service import OrderService
from support_agent.retrieval.scope import scope_chunks

logger = logging.getLogger(__name__)
ORDER_ID = re.compile(r"\bORD[- ]?\d{6}\b", re.IGNORECASE)
CITATION = re.compile(r"\[(\d+)\]")


class RefundDecision(BaseModel):
    eligible: Literal["yes", "no", "needs_human"]
    items: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    citations: list[int] = Field(default_factory=list)


class RefundPath:
    def __init__(self, deps: GraphDeps) -> None:
        self.deps = deps
        self.prompt = (PROMPTS / "refund_decide.md").read_text(encoding="utf-8")

    def _service(self) -> OrderService:
        return self.deps.order_service or OrderService(settings=self.deps.settings.orders)

    def identify_order(self, state: ConversationState) -> dict[str, Any]:
        service = self._service()
        query = " ".join(
            message.content for message in state.messages if isinstance(message.content, str)
        )
        match = ORDER_ID.search(query)
        order_id = match.group(0).upper().replace(" ", "-") if match else None
        if order_id is None:
            try:
                response = self.deps.model("fast").invoke(
                    [
                        SystemMessage(
                            content="Extract an order id from the customer request. "
                            "Return the id or say none."
                        ),
                        HumanMessage(content=query),
                    ]
                )
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
        try:
            orders = service.list_recent_orders(state.customer_id or "")
        except (FileNotFoundError, ValueError):
            return {
                **make_handoff(state.model_copy(deep=True), HandoffReason.ORDER_NOT_FOUND),
                "trace": [*state.trace, "after_sales", "refund_identify", "handoff"],
            }
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

    def load_order(self, state: ConversationState) -> dict[str, Any]:
        if not state.refund_order_id or not state.customer_id:
            return self._handoff(state, HandoffReason.ORDER_NOT_FOUND)
        try:
            order = self._service().get_order(state.refund_order_id, state.customer_id)
        except (OrderNotFound, ValueError):
            return self._handoff(state, HandoffReason.ORDER_NOT_FOUND)
        today = self.deps.settings.orders.today
        days = (today - order.delivered_at).days if order.delivered_at else None
        context = {
            "order": order.model_dump(mode="json"),
            "days_since_delivery": days,
            "today": today.isoformat(),
        }
        return {"order_context": context, "trace": [*state.trace, "refund_load"]}

    def retrieve_policy(self, state: ConversationState) -> dict[str, Any]:
        order = self._order_from_state(state)
        if order is None:
            return self._handoff(state, HandoffReason.ORDER_NOT_FOUND)
        settings = self.deps.settings
        query = policy_query(order, state.intent.value if state.intent else None, settings)
        retrieval = settings.retrieval
        scope = retrieval.store_scope
        pool = (
            max(retrieval.rerank_top_k, scope.pool_k) if scope.enabled else retrieval.rerank_top_k
        )
        try:
            ranked = self.deps.knowledge_retriever().retrieve(query, pool)
            chunks, _, _ = scope_chunks(query, ranked, scope, retrieval.rerank_top_k)
        except Exception as error:
            logger.warning("Refund policy retrieval failed: %s", type(error).__name__)
            chunks = []
        gate = evaluate(
            query,
            chunks,
            self.deps.settings.gate,
            allow_untuned=self.deps.allow_untuned_gate,
        )
        if not gate.passed:
            current = state.model_copy(update={"retrieval": chunks, "gate": gate}, deep=True)
            return {
                **make_handoff(current, HandoffReason.LOW_EVIDENCE),
                "retrieval": chunks,
                "gate": gate,
                "refund_policy_query": query,
                "trace": [*state.trace, "refund_retrieve", "handoff"],
            }
        return {
            "retrieval": chunks,
            "gate": gate,
            "refund_policy_query": query,
            "trace": [*state.trace, "refund_retrieve"],
        }

    def decide(self, state: ConversationState) -> dict[str, Any]:
        order = self._order_from_state(state)
        if order is None or state.gate is None or not state.gate.passed:
            return self._handoff(state, HandoffReason.POLICY_REQUIRES_HUMAN)
        sources = self._sources(state)
        messages = [
            SystemMessage(content=self.prompt),
            HumanMessage(
                content=(
                    f"Order facts:\n{json.dumps(state.order_context, sort_keys=True)}\n\n"
                    f"Sources:\n{sources}"
                )
            ),
        ]
        try:
            model = self.deps.model("main")
            structured = model.with_structured_output(RefundDecision, include_raw=True)
            raw = structured.invoke(messages)
            decision = self._parse_decision(raw)
        except Exception as error:
            logger.warning("Refund decision failed: %s", type(error).__name__)
            return self._handoff(state, HandoffReason.POLICY_REQUIRES_HUMAN)
        decision = self._check_decision(decision, order, state)
        return {
            "refund_decision": decision.model_dump(),
            "trace": [*state.trace, "refund_decide"],
        }

    def act(self, state: ConversationState) -> dict[str, Any]:
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
        if decision.eligible == "no":
            reason = " ".join(decision.reasons) or "The policy does not support this request."
            answer = (
                f"I cannot approve this request. {reason} "
                f"You can ask a human agent to review it. {citations}"
            ).strip()
            return {
                "answer": answer,
                "citations": records,
                "messages": [AIMessage(content=answer)],
                "trace": [*state.trace, "refund_act"],
            }
        if not state.refund_order_id or not state.customer_id:
            return self._handoff(state, HandoffReason.ORDER_NOT_FOUND)
        try:
            request = self._service().create_refund_request(
                state.refund_order_id,
                state.customer_id,
                decision.items,
                "; ".join(decision.reasons) or "Customer refund request",
            )
        except Exception as error:
            logger.warning("Refund request creation failed: %s", type(error).__name__)
            return self._handoff(state, HandoffReason.POLICY_REQUIRES_HUMAN)
        answer = (
            f"Your refund request {request.request_id} is pending human review. {citations}".strip()
        )
        return {
            "refund_request": request.model_dump(mode="json"),
            "answer": answer,
            "citations": records,
            "messages": [AIMessage(content=answer)],
            "trace": [*state.trace, "refund_act"],
        }

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
    def _sources(state: ConversationState) -> str:
        return "\n\n".join(
            f"[{index}] {chunk.heading_path}\n{chunk.text}"
            for index, chunk in enumerate(state.retrieval, start=1)
        )

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
        valid_citations = sorted(
            {number for number in decision.citations if 1 <= number <= len(state.retrieval)}
        )
        valid_items = {
            item.item_id for item in order.items if item.refunded_quantity < item.quantity
        }
        cited_numbers = {
            int(number) for reason in decision.reasons for number in CITATION.findall(reason)
        }
        cited_chunks = [
            state.retrieval[number - 1] for number in valid_citations if number in cited_numbers
        ]
        reasons_cited = bool(decision.reasons) and all(
            any(number in valid_citations for number in map(int, CITATION.findall(reason)))
            for reason in decision.reasons
        )
        if decision.eligible == "yes" and (
            not reasons_cited
            or not valid_citations
            or not decision.items
            or not set(decision.items) <= valid_items
        ):
            return decision.model_copy(
                update={"eligible": "needs_human", "citations": valid_citations}
            )
        if decision.eligible == "no" and (not reasons_cited or not valid_citations):
            return decision.model_copy(
                update={"eligible": "needs_human", "citations": valid_citations}
            )
        selected_items = set(decision.items)
        if decision.eligible == "yes" and any(
            item.final_sale and item.item_id in selected_items for item in order.items
        ):
            policy_text = " ".join(chunk.text.casefold() for chunk in cited_chunks)
            if "final sale" not in policy_text and "final-sale" not in policy_text:
                return decision.model_copy(
                    update={"eligible": "needs_human", "citations": valid_citations}
                )
        if decision.eligible == "yes" and order.status.value not in {
            "delivered",
            "partially_refunded",
        }:
            policy_text = " ".join(chunk.text.casefold() for chunk in cited_chunks)
            if order.status.value.replace("_", " ") not in policy_text:
                return decision.model_copy(
                    update={"eligible": "needs_human", "citations": valid_citations}
                )
        if valid_citations != decision.citations:
            return decision.model_copy(
                update={"eligible": "needs_human", "citations": valid_citations}
            )
        return decision

    @staticmethod
    def _handoff(state: ConversationState, reason: HandoffReason) -> dict[str, Any]:
        current = state.model_copy(deep=True)
        current.trace.append("handoff")
        return {**make_handoff(current, reason), "trace": current.trace}
