# ==============================================================================
# Analytics Engine Dockerfile (FastAPI + Streamlit Dashboard)
# ==============================================================================
FROM python:3.11-slim

WORKDIR /app

# Prevent Python from writing bytecode and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ANALYTICS_DB_PATH=/app/data/analytics.db \
    ANALYTICS_URL=http://localhost:8000

# Install curl for health checking and dos2unix to guarantee Unix line endings
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    dos2unix \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency specifications first for layer caching
COPY requirements.txt ./
COPY dashboard/requirements.txt ./dashboard-requirements.txt

# Install API and dashboard python packages
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -r dashboard-requirements.txt

# Create directory for persistent SQLite database
RUN mkdir -p /app/data

# Copy application source code
COPY . .

# Normalize line endings and permissions for the entrypoint script
RUN dos2unix /app/start.sh && chmod +x /app/start.sh

# Expose FastAPI (8000) and Streamlit (8501)
EXPOSE 8000 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["/app/start.sh"]
