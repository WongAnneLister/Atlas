# Multi-stage production image for Atlas support-agent API.
# Non-root user, pinned uv.lock dependencies, zero secrets baked into the image.

FROM python:3.11-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONDONTWRITEBYTECODE=1

RUN pip install --no-cache-dir uv==0.5.26

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY configs ./configs
COPY migrations ./migrations
COPY alembic.ini ./

RUN uv sync --frozen --no-dev --extra postgres --extra deepseek --extra tracing


FROM python:3.11-slim AS runtime

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/app/.cache/huggingface \
    ENV=prod

RUN groupadd --system atlas && useradd --system --gid atlas --create-home atlas

WORKDIR /app
COPY --from=builder --chown=atlas:atlas /app/.venv /app/.venv
COPY --from=builder --chown=atlas:atlas /app/src /app/src
COPY --from=builder --chown=atlas:atlas /app/configs /app/configs
COPY --from=builder --chown=atlas:atlas /app/migrations /app/migrations
COPY --from=builder --chown=atlas:atlas /app/alembic.ini /app/alembic.ini

RUN mkdir -p /app/.cache/huggingface /app/data/processed && chown -R atlas:atlas /app/.cache /app/data

USER atlas
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health/live', timeout=3)"

CMD ["uvicorn", "support_agent.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
