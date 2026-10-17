# Multi-stage build: the compile toolchain (needed by some of the routing
# library's dependencies) stays in the builder stage only.

FROM python:3.10-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first (including the llmrouter-lib package from PyPI), with
# only a stub package present, so this layer is cached across source edits.
COPY pyproject.toml ./
RUN mkdir backend && touch backend/__init__.py
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.10-slim

WORKDIR /app

COPY --from=builder /install /usr/local

COPY backend/ backend/
COPY configs/ configs/
COPY data/ data/
COPY scripts/ scripts/
COPY alembic.ini alembic.ini

ENV PYTHONPATH=/app
ENV BACKEND_HOST=0.0.0.0
ENV BACKEND_PORT=8080

EXPOSE 8080

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8080"]
