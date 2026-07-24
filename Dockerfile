ARG BASE_PY_IMAGE=docker.m.daocloud.io/library/python:3.11-slim-bookworm
FROM ${BASE_PY_IMAGE}

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG APT_DEBIAN_MIRROR=http://deb.debian.org/debian
ARG APT_SECURITY_MIRROR=http://deb.debian.org/debian-security
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
    sed -i "s|http://deb.debian.org/debian-security|${APT_SECURITY_MIRROR}|g; s|http://deb.debian.org/debian|${APT_DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-chi-sim \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

RUN HTTP_PROXY="${HTTP_PROXY}" HTTPS_PROXY="${HTTPS_PROXY}" ALL_PROXY="${ALL_PROXY}" \
    PIP_NO_CACHE_DIR=0 python -m pip install --retries 5 --upgrade pip setuptools wheel \
    && HTTP_PROXY="${HTTP_PROXY}" HTTPS_PROXY="${HTTPS_PROXY}" ALL_PROXY="${ALL_PROXY}" \
    PIP_NO_CACHE_DIR=0 pip install --retries 5 -r /app/requirements.txt

COPY src/ /app/src/
COPY pyproject.toml /app/pyproject.toml

EXPOSE 8000

CMD ["uvicorn", "gp_assistant.gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]
