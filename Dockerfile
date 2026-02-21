FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=100

# 可选：构建时指定 pip 镜像源（国内可用清华/阿里等）
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL}

WORKDIR /app

# Install Python deps first (cacheable)
COPY requirements.txt /app/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    PIP_NO_CACHE_DIR=0 python -m pip install --upgrade pip setuptools wheel \
    && PIP_NO_CACHE_DIR=0 pip install -r /app/requirements.txt

# Copy only source and minimal metadata; avoid copying bulky folders
COPY src/ /app/src/
COPY pyproject.toml /app/pyproject.toml

# Allow importing from src without editable install
ENV PYTHONPATH=/app/src

ENV TZ=Asia/Shanghai
EXPOSE 8000

CMD ["uvicorn","gp_assistant.server.app:app","--host","0.0.0.0","--port","8000"]
