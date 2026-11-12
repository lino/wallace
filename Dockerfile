# syntax=docker/dockerfile:1
FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src

RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    WALLACE_IDE_DIR="/data/antigravity" \
    WALLACE_CLI_DIR="/data/antigravity-cli" \
    WALLACE_METRICS_HOST="0.0.0.0" \
    WALLACE_METRICS_PORT="9464"

RUN groupadd --gid 10001 wallace \
    && useradd --uid 10001 --gid wallace --create-home --shell /usr/sbin/nologin wallace

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY schemas ./schemas
COPY man ./man

USER wallace
EXPOSE 9464

ENTRYPOINT ["wallace"]
CMD ["report", "summary"]
