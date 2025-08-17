FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Create non-root user
RUN useradd -m -u 10001 appuser

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy app
COPY app /app/app
COPY healthcheck.py /app/healthcheck.py

# Create data dir and set permissions
RUN mkdir -p /data && chown -R appuser:appuser /data /app

USER appuser

ENV PYTHONPATH=/app

# Default command
CMD ["python", "-m", "app.main"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
 CMD python /app/healthcheck.py || exit 1