FROM debian:12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update -y && apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3-pip \
    build-essential libffi-dev libssl-dev \
    ca-certificates curl && \
    update-ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./

RUN python3.11 -m pip install --no-cache-dir --upgrade pip && \
    python3.11 -m pip install --no-cache-dir -e .

COPY app ./app

CMD ["python3.11", "-m", "app"]
