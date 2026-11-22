# DoD Budget Explorer — Streamlit app image
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/app/.hf-cache \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=none

WORKDIR /app

# The manifest selects CPU-only torch, including on hosts that install it
# directly rather than building this image.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && python -c "import torch; assert torch.version.cuda is None"

COPY . .

# Ship the weights as well as the prebuilt indexes. Retrieval must work before
# anyone has searched, and must not depend on network access after deployment.
RUN python scripts/cache_model.py
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://localhost:' + os.environ.get('PORT', '8501') + '/_stcore/health')"

CMD ["sh", "-c", "exec python -m streamlit run app.py --server.port=${PORT:-8501} --server.address=0.0.0.0 --server.headless=true"]
