FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

# Install the src/ package so gp_assistant, gpbt are importable via module paths
RUN pip install -e .

CMD ["python","assistant.py","chat"]
