FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir fastapi uvicorn lightgbm pandas pyarrow "feast[postgres]"
WORKDIR /app
COPY README.md /app/README.md
COPY p2-forecasting/probe_app.py /app/probe_app.py
CMD ["sh", "-c", "uvicorn probe_app:app --host 0.0.0.0 --port ${PORT:-8000}"]
