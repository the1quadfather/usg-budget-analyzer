# Dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Tell HuggingFace to cache models inside the image
ENV HF_HOME=/app/.cache/huggingface
ENV SENTENCE_TRANSFORMERS_HOME=/app/.cache/sentence_transformers

WORKDIR /app

# System deps: build tools + poppler-utils (provides pdftotext)
RUN apt-get update && apt-get install -y \
    build-essential \
    poppler-utils \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (layer cache friendly)
COPY requirements.txt .
# Cache bust: 2026-03-27
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code and processed data
COPY . .

# Verify required data files exist
RUN test -f data/processed/usg_budgets.db || \
    (echo "ERROR: data/processed/usg_budgets.db not found. Run ingest first." && exit 1)

ENV PORT=8501
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["python", "-m", "streamlit", "run", "app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]