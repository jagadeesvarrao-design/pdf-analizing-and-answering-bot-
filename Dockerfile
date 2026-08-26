# ==============================================================================
# Aneevarp DocAI - Google Cloud Run Production Dockerfile
# Built by Aneevarp Solutions for Google Cloud Gen AI Ideathon
# ==============================================================================

FROM python:3.11-slim

# Set Python environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /app

# Install essential system dependencies for PyMuPDF & C extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -U pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application files (FastAPI backend + Static Frontend)
COPY . .

# Create non-root user for container security hardening
RUN useradd -m -u 1000 appuser && \
    mkdir -p temp_pdfs faiss_index && \
    chown -R appuser:appuser /app
USER appuser

# Expose Cloud Run default port
EXPOSE 8080

# Run Uvicorn listening on Cloud Run's dynamic $PORT
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT}
