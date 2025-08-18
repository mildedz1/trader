FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update -y && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .[dev]

COPY app ./app

CMD ["python", "-m", "app"]
