# Stage 1: build the React app
FROM node:24-slim AS frontend
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Shared python base with uv. The venv lives outside /app so bind-mounting the source in dev
# doesn't hide it.
FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# Stage 2a: dev/tools image (pytest, ruff). Source is bind-mounted by docker compose.
FROM base AS dev
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-install-project
CMD ["fastapi", "dev", "--host", "0.0.0.0", "--port", "8000"]

# Stage 2b (default, last): production runtime
FROM base AS runtime
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend/ ./
COPY --from=frontend /frontend/dist /app/static
EXPOSE 8000
CMD ["sh", "-c", "fastapi run --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
