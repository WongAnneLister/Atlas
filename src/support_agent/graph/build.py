"""Compile the fixed rewrite → classify → path workflow with checkpointing."""

from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send

from support_agent.graph.deps import GraphDeps
from support_agent.graph.intents import INTENT_TO_PATH, PATH_NODES, Path
from support_agent.graph.nodes.classify import Classifier
from support_agent.graph.nodes.complaint import ComplaintPath
from support_agent.graph.nodes.fixed import fixed_reply
from support_agent.graph.nodes.input_guard import InputGuard
from support_agent.graph.nodes.knowledge import KnowledgePath, route_after_gate
from support_agent.graph.nodes.output_guard import OutputGuard
from support_agent.graph.nodes.part_retrieval import PartKnowledgeRetrieval, route_after_parts_gate
from support_agent.graph.nodes.plan import Planner
from support_agent.graph.nodes.refund import RefundPath
from support_agent.graph.nodes.rewrite import make_rewrite_node
from support_agent.graph.nodes.tools_path import ToolsPath
from support_agent.graph.parts import PartRetrievalRequest
from support_agent.graph.state import ConversationState
from support_agent.reliability.events import collect_events


def route_by_path(state: ConversationState) -> str:
    """Select the fixed path after classification without adding a trace node."""
    if state.path is None:
        raise ValueError("Classification must set a path before routing")
    if state.path == Path.KNOWLEDGE:
        return "retrieve"
    return PATH_NODES[state.path]


def dispatch_after_classify(state: ConversationState) -> str | list[Send]:
    if state.route_source != "parts":
        return route_by_path(state)
    return [
        Send(
            "retrieve_part",
            PartRetrievalRequest(
                index=index, text=part.text, rewritten_query=state.rewritten_query
            ),
        )
        for index, part in enumerate(state.parts)
        if part.intent is not None and INTENT_TO_PATH[part.intent] == Path.KNOWLEDGE
    ]


def route_after_tools(state: ConversationState) -> str:
    """A question the order loop did not treat as a lookup goes through retrieval."""
    return "retrieve" if state.fallback_to_knowledge else "output_guard"


def route_refund_identify(state: ConversationState) -> str:
    return "refund_load" if state.refund_order_id else "output_guard"


def route_refund_policy(state: ConversationState) -> str:
    return "refund_decide" if state.gate is not None and state.gate.passed else "output_guard"


def _stub(path: Path, name: str) -> Callable[[ConversationState], dict[str, Any]]:
    def run(state: ConversationState) -> dict[str, Any]:
        answer = f"[path {path.value} not implemented]"
        return {
            "answer": answer,
            "messages": [AIMessage(content=answer)],
            "trace": [*state.trace, name],
        }

    return run


def _recording_node(
    node: Callable[[ConversationState], dict[str, Any]],
    *,
    publishes_reply: bool,
) -> Callable[[ConversationState], dict[str, Any]]:
    def run(state: ConversationState) -> dict[str, Any]:
        with collect_events() as events:
            update = node(state)
        if not publishes_reply and update.get("answer"):
            # Keep unchecked drafts out of the history even if the graph stops here.
            update["messages"] = [
                message
                for message in update.get("messages", [])
                if not isinstance(message, AIMessage)
            ]
        if events:
            update["reliability_events"] = [
                *update.get("reliability_events", state.reliability_events),
                *events,
            ]
            models = dict(update.get("answered_by_model", state.answered_by_model))
            for event in events:
                if event.role and event.model and event.error_type is None:
                    models[event.call_site] = event.model
            update["answered_by_model"] = models
        return update

    return run


def build_graph(deps: GraphDeps) -> CompiledStateGraph[ConversationState, None, Any, Any]:
    """The dependency owner must remain open for the graph's entire lifetime."""
    graph = StateGraph(ConversationState)

    def add_node(name: str, node: Callable[[ConversationState], dict[str, Any]]) -> None:
        graph.add_node(
            name, RunnableLambda(_recording_node(node, publishes_reply=name == "output_guard"))
        )

    add_node("input_guard", InputGuard(deps))
    add_node("rewrite", make_rewrite_node(deps.models, deps.settings))
    add_node("classify", Classifier(None, deps.settings, models=deps.models))
    graph.add_edge(START, "input_guard")
    graph.add_conditional_edges(
        "input_guard",
        lambda state: "output_guard" if state.input_guard_action == "block" else "rewrite",
        ["rewrite", "output_guard"],
    )
    if deps.settings.planning.enabled:
        add_node("plan", Planner(deps))
        graph.add_edge("rewrite", "plan")
        graph.add_edge("plan", "classify")
    else:
        graph.add_edge("rewrite", "classify")
    graph.add_conditional_edges(
        "classify",
        dispatch_after_classify,
        [name for path, name in PATH_NODES.items() if path != Path.KNOWLEDGE]
        + ["retrieve", "retrieve_part"],
    )
    implementations: dict[Path, Callable[[ConversationState], dict[str, Any]]] = {
        Path.TOOLS: ToolsPath(deps),
        Path.COMPLAINT: ComplaintPath(deps),
        Path.FIXED: fixed_reply,
    }
    knowledge = KnowledgePath(deps)
    refund = RefundPath(deps)
    parts = PartKnowledgeRetrieval(deps)
    graph.add_node(
        "retrieve_part", RunnableLambda(parts.retrieve_part), input_schema=PartRetrievalRequest
    )
    add_node("merge", parts.merge)
    add_node("gate_parts", parts.gate_parts)
    graph.add_edge("retrieve_part", "merge")
    graph.add_edge("merge", "gate_parts")
    graph.add_conditional_edges("gate_parts", route_after_parts_gate, ["answer", "handoff"])
    add_node("retrieve", knowledge.retrieve)
    add_node("gate", knowledge.gate)
    add_node("answer", knowledge.answer)
    add_node("handoff", knowledge.handoff)
    graph.add_edge("retrieve", "gate")
    graph.add_conditional_edges("gate", route_after_gate, ["answer", "handoff"])
    graph.add_edge("answer", "output_guard")
    graph.add_edge("handoff", "output_guard")
    add_node("refund_load", refund.load_order)
    add_node("refund_retrieve", refund.retrieve_policy)
    add_node("refund_decide", refund.decide)
    add_node("refund_act", refund.act)
    graph.add_edge("refund_load", "refund_retrieve")
    graph.add_conditional_edges(
        "refund_retrieve", route_refund_policy, ["refund_decide", "output_guard"]
    )
    graph.add_edge("refund_decide", "refund_act")
    graph.add_edge("refund_act", "output_guard")
    for path, name in PATH_NODES.items():
        if path == Path.KNOWLEDGE:
            continue
        if path == Path.AFTER_SALES:
            add_node(name, refund.identify_order)
            graph.add_conditional_edges(
                name, route_refund_identify, ["refund_load", "output_guard"]
            )
            continue
        add_node(name, implementations.get(path, _stub(path, name)))
        if path == Path.TOOLS:
            graph.add_conditional_edges(name, route_after_tools, ["retrieve", "output_guard"])
        else:
            graph.add_edge(name, "output_guard")
    add_node("output_guard", OutputGuard(deps))
    graph.add_edge("output_guard", END)
    return graph.compile(checkpointer=deps.checkpointer())
