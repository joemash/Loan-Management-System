FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
# Fail a stalled download after 2 minutes instead of hanging; retry transient network errors.
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_HTTP_TIMEOUT=120 UV_HTTP_RETRIES=5
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
# The cache mount keeps downloaded wheels between builds, so a retry only fetches what is missing.
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY --from=build /app /app
COPY alembic.ini entrypoint.sh ./
COPY migrations ./migrations
RUN chmod +x entrypoint.sh && useradd --system --uid 1001 lms
USER lms
EXPOSE 8080
ENTRYPOINT ["./entrypoint.sh"]
