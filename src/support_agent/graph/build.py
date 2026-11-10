"""Compile the fixed rewrite → classify → path workflow with checkpointing."""

from collections.abc import Callable
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from support_agent.graph.deps import GraphDeps
from support_agent.graph.intents import PATH_NODES, Path
from support_agent.graph.nodes.classify import Classifier
from support_agent.graph.nodes.complaint import ComplaintPath
from support_agent.graph.nodes.fixed import fixed_reply
from support_agent.graph.nodes.knowledge import KnowledgePath, route_after_gate
from support_agent.graph.nodes.rewrite import make_rewrite_node
from support_agent.graph.nodes.tools_path import ToolsPath
from support_agent.graph.state import ConversationState


def route_by_path(state: ConversationState) -> str:
    """Select the fixed path after classification without adding a trace node."""
    if state.path is None:
        raise ValueError("Classification must set a path before routing")
    if state.path == Path.KNOWLEDGE:
        return "retrieve"
    return PATH_NODES[state.path]


def _stub(path: Path, name: str) -> Callable[[ConversationState], dict[str, Any]]:
    def run(state: ConversationState) -> dict[str, Any]:
        answer = f"[path {path.value} not implemented]"
        return {
            "answer": answer,
            "messages": [AIMessage(content=answer)],
            "trace": [*state.trace, name],
        }

    return run


def build_graph(deps: GraphDeps) -> CompiledStateGraph[ConversationState, None, Any, Any]:
    """The dependency owner must remain open for the graph's entire lifetime."""
    model = deps.model()
    graph = StateGraph(ConversationState)
    graph.add_node("rewrite", RunnableLambda(make_rewrite_node(model, deps.settings)))
    graph.add_node("classify", Classifier(model, deps.settings))
    graph.add_edge(START, "rewrite")
    graph.add_edge("rewrite", "classify")
    graph.add_conditional_edges(
        "classify",
        route_by_path,
        [name for path, name in PATH_NODES.items() if path != Path.KNOWLEDGE] + ["retrieve"],
    )
    implementations: dict[Path, Callable[[ConversationState], dict[str, Any]]] = {
        Path.TOOLS: ToolsPath(deps),
        Path.COMPLAINT: ComplaintPath(deps),
        Path.FIXED: fixed_reply,
    }
    knowledge = KnowledgePath(deps)
    graph.add_node("retrieve", RunnableLambda(knowledge.retrieve))
    graph.add_node("gate", RunnableLambda(knowledge.gate))
    graph.add_node("answer", RunnableLambda(knowledge.answer))
    graph.add_node("handoff", RunnableLambda(knowledge.handoff))
    graph.add_edge("retrieve", "gate")
    graph.add_conditional_edges("gate", route_after_gate, ["answer", "handoff"])
    graph.add_edge("answer", END)
    graph.add_edge("handoff", END)
    for path, name in PATH_NODES.items():
        if path == Path.KNOWLEDGE:
            continue
        graph.add_node(name, RunnableLambda(implementations.get(path, _stub(path, name))))
        graph.add_edge(name, END)
    return graph.compile(checkpointer=deps.checkpointer())
