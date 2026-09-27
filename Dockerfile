FROM python:3.11-slim

# System deps for scipy/numpy native extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py .

# Copy pre-computed model artifacts (not retrained in container — artifact dir is baked in)
COPY artifacts/ ./artifacts/

# Copy static frontend
COPY static/ ./static/

ENV ARTIFACT_DIR=./artifacts
ENV PORT=8000

EXPOSE 8000

# $PORT is injected by Render/Cloud Run; fall back to 8000 for local docker run
CMD uvicorn app:app --host 0.0.0.0 --port ${PORT:-8000}
