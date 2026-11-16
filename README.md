![Support Agent: an after-sales AI agent that answers with citations and hands off to a human when the evidence is weak](docs/assets/cover.png)

# support-agent

An English e-commerce after-sales support agent.
It uses LangGraph, hybrid retrieval (BGE-M3 + BM25 + RRF + rerank) and an evidence gate.
When the evidence is weak, it hands off to a human instead of guessing.

Status: work in progress. See `docs/PROGRESS.md`.

    make setup   # install with uv
    make up      # start Milvus (Docker)
    make check   # lint, types, tests, interview-note check

Run the demo with `make serve`. The demo app has no authentication and trusts the supplied customer ID.
