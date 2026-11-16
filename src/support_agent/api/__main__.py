"""Serve the local chat demo."""

import logging

import uvicorn
from dotenv import load_dotenv

from support_agent.api.app import create_app
from support_agent.api.deps import ApiDeps
from support_agent.config import get_settings
from support_agent.graph.deps import GraphDeps
from support_agent.orders.service import OrderService
from support_agent.retrieval.milvus_store import MilvusStore


def main() -> None:
    load_dotenv()
    settings = get_settings()
    api = settings.api
    service = OrderService(settings=settings.orders)

    def milvus_check() -> bool:
        store = MilvusStore(settings)
        try:
            return bool(store.server_version())
        finally:
            store.close()

    deps = ApiDeps(
        settings,
        GraphDeps(settings, order_service=service),
        service,
        milvus_check,
        warmup=api.warmup_retriever,
    )
    logging.basicConfig(level=logging.INFO)
    logging.getLogger(__name__).info("Chat demo at http://%s:%s/", api.host, api.port)
    uvicorn.run(create_app(deps), host=api.host, port=api.port, reload=False)


if __name__ == "__main__":
    main()
