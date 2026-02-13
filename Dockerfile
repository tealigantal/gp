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

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip setuptools wheel \
 && pip install -r /app/requirements.txt

COPY . /app
RUN pip install -e .

ENV TZ=Asia/Shanghai
EXPOSE 8000

CMD ["uvicorn","gp_assistant.server.app:app","--host","0.0.0.0","--port","8000"]
