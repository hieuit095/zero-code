# ─── Backend (FastAPI Orchestrator + MCP Facade) ──────────────────────────────
FROM python:3.12-slim AS backend

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY worker.py ./

# Expose only the API port (MCP facade is internal — Rule 3)
EXPOSE 8000

# Run with production settings
ENV PYTHONUNBUFFERED=1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
