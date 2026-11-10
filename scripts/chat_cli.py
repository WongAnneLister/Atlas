"""Small local REPL over the graph; customer identity is a trusted CLI argument."""

from __future__ import annotations

import argparse
import logging
import os
from uuid import uuid4

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langgraph.types import Command

from support_agent.config import get_settings
from support_agent.graph.build import build_graph
from support_agent.graph.deps import GraphDeps
from support_agent.orders.service import OrderService


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--customer", required=True, help="Trusted mock customer id")
    parser.add_argument("--question", default=os.environ.get("Q", ""))
    parser.add_argument(
        "--allow-untuned-gate",
        action="store_true",
        help="Use the configured placeholder gate threshold for local demos",
    )
    args = parser.parse_args(argv)
    if not args.customer.strip():
        parser.error("--customer must be nonempty")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = get_settings()
    with GraphDeps(
        settings,
        order_service=OrderService(settings=settings.orders),
        allow_untuned_gate=args.allow_untuned_gate,
    ) as deps:
        try:
            graph = build_graph(deps)
            config = {"configurable": {"thread_id": f"{args.customer}:{uuid4().hex}"}}
            while True:
                question = args.question or input("You (or /quit): ").strip()
                if question == "/quit":
                    break
                if not question:
                    continue
                result = graph.invoke(
                    {"messages": [HumanMessage(content=question)], "customer_id": args.customer},
                    config,
                )
                while result.get("__interrupt__"):
                    interruption = result["__interrupt__"][0]
                    payload = interruption.value
                    if payload.get("type") != "order_picker":
                        raise RuntimeError("Unsupported graph interrupt")
                    print("Choose an order:")
                    for order in payload["orders"]:
                        print(
                            f"  {order['order_id']} | {order['order_date']} | "
                            f"{order['status']} | {order['total']} {order['currency']}"
                        )
                    choice = input("Order id (or none): ").strip()
                    result = graph.invoke(Command(resume=choice), config)
                print(f"Agent: {result['answer']}")
                print(f"Trace: {' -> '.join(result['trace'])}")
                if result.get("handoff"):
                    payload = result["handoff"]
                    reason = payload.reason if hasattr(payload, "reason") else payload["reason"]
                    print(f"Handoff: {reason}")
                if args.question:
                    break
        except (EOFError, KeyboardInterrupt):
            pass
        except Exception as error:
            logging.getLogger(__name__).error("Chat failed: %s", type(error).__name__)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
