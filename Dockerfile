FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /uvx /bin/
WORKDIR /app
ENV UV_LINK_MODE=copy PYTHONDONTWRITEBYTECODE=1
COPY pyproject.toml README.md LICENSE ./
COPY agenteval ./agenteval
COPY tests ./tests
COPY docs ./docs
RUN uv sync --group dev
CMD ["uv", "run", "pytest"]
