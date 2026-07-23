ARG BASE_PY_IMAGE=docker.m.daocloud.io/library/python:3.11-slim-bookworm
FROM ${BASE_PY_IMAGE}

ARG PIP_INDEX_URL=https://pypi.org/simple
# Proxies are optional build inputs. Never default to a host-specific port:
# Docker Desktop and local proxy clients can change independently.
ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG ALL_PROXY
ARG GP_BUILD_REVISION=local

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_ROOT_USER_ACTION=ignore \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    GP_BUILD_REVISION=${GP_BUILD_REVISION} \
    PYTHONPATH=/app/src \
    TZ=Asia/Shanghai

LABEL org.opencontainers.image.revision=${GP_BUILD_REVISION} \
      io.gp.artifact-schema="ContractKernel.v1" \
      io.gp.selection-policy="adaptive_kernel_v2"

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN HTTP_PROXY="${HTTP_PROXY}" HTTPS_PROXY="${HTTPS_PROXY}" ALL_PROXY="${ALL_PROXY}" \
    PIP_NO_CACHE_DIR=0 python -m pip install --upgrade pip setuptools wheel \
    && HTTP_PROXY="${HTTP_PROXY}" HTTPS_PROXY="${HTTPS_PROXY}" ALL_PROXY="${ALL_PROXY}" \
    PIP_NO_CACHE_DIR=0 pip install -r /app/requirements.txt

COPY src/ /app/src/
COPY pyproject.toml /app/pyproject.toml

EXPOSE 8000

CMD ["uvicorn", "gp_assistant.gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]
