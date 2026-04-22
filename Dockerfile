# syntax=docker/dockerfile:1.7

FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_ROOT_USER_ACTION=ignore \
    PYTHONPATH=/app/src \
    TZ=Asia/Shanghai

ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL}

WORKDIR /app

RUN apt-get update -o Acquire::Retries=3 \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt

RUN --mount=type=cache,target=/root/.cache/pip \
    PIP_NO_CACHE_DIR=0 python -m pip install --upgrade pip setuptools wheel \
    && PIP_NO_CACHE_DIR=0 pip install -r /app/requirements.txt

COPY src/ /app/src/
COPY pyproject.toml /app/pyproject.toml

EXPOSE 8000

CMD ["uvicorn", "gp_assistant.server.app:app", "--host", "0.0.0.0", "--port", "8000"]