# GitHub repository settings (for the human to apply)

These are suggestions. Apply them in the repository's **About** panel on GitHub.

## Description

> After-sales support agent (LangGraph): hybrid retrieval, an evidence gate, cited answers, and human handoff when evidence is weak. Every metric comes from a re-runnable eval.

## Website

Leave empty until the demo video is public. Then use the video link.

## Topics

`langgraph`, `rag`, `retrieval-augmented-generation`, `hybrid-search`, `bm25`, `reranking`,
`milvus`, `bge-m3`, `fastapi`, `server-sent-events`, `customer-support`, `llm-evaluation`,
`hallucination`, `langfuse`, `python`

## Other settings

- Social preview image: `docs/assets/cover.png`.
- Turn off Wiki and Projects; the docs live in `docs/`.
- Issue templates are not needed.
- Before making the repo public, check that no `.env`, `data/raw/`, `.sqlite` or model files are tracked:
  `git ls-files | grep -E '\.env$|data/raw/|\.sqlite$|\.safetensors$'` should print nothing.
