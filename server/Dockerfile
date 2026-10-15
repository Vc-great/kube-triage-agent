FROM python:3.13.14-slim-bookworm
COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable
COPY aegra.json ./
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 AEGRA_CONFIG=/app/aegra.json
EXPOSE 2026
CMD ["sh", "-c", "python -m kube_triage.config && python -c 'from kube_triage.auth import auth' && exec aegra serve --host 0.0.0.0 --port 2026"]
