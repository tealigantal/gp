ARG BASE_PY_IMAGE=docker.m.daocloud.io/library/python:3.11-slim-bookworm
FROM ${BASE_PY_IMAGE}

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG HTTP_PROXY=http://host.docker.internal:7890
ARG HTTPS_PROXY=http://host.docker.internal:7890
ARG ALL_PROXY=http://host.docker.internal:7890
ARG GP_BUILD_REVISION=local

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_ROOT_USER_ACTION=ignore \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    HTTP_PROXY=${HTTP_PROXY} \
    HTTPS_PROXY=${HTTPS_PROXY} \
    ALL_PROXY=${ALL_PROXY} \
    GP_BUILD_REVISION=${GP_BUILD_REVISION} \
    PYTHONPATH=/app/src \
    TZ=Asia/Shanghai

LABEL org.opencontainers.image.revision=${GP_BUILD_REVISION} \
      io.gp.artifact-schema="gp.runtime-artifact.v2" \
      io.gp.selection-policy="adaptive_policy_single_path"

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN PIP_NO_CACHE_DIR=0 python -m pip install --upgrade pip setuptools wheel \
    && PIP_NO_CACHE_DIR=0 pip install -r /app/requirements.txt

COPY src/ /app/src/
COPY pyproject.toml /app/pyproject.toml

EXPOSE 8000

CMD ["uvicorn", "gp_assistant.gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]
