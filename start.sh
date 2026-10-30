#!/bin/sh
set -e

if [ "$1" = "fastapi" ]; then
    echo "Starting FastAPI Analytics Engine on port 8000..."
    exec uvicorn main:app --host 0.0.0.0 --port 8000
elif [ "$1" = "streamlit" ]; then
    echo "Starting Streamlit Dashboard on port 8501..."
    exec streamlit run dashboard/app.py --server.port=8501 --server.address=0.0.0.0 --server.headless=true --browser.gatherUsageStats=false
elif [ $# -gt 0 ]; then
    exec "$@"
else
    echo "Starting FastAPI Analytics Engine in background on port 8000..."
    uvicorn main:app --host 0.0.0.0 --port 8000 &

    echo "Waiting for FastAPI to become ready..."
    COUNT=0
    while ! curl -s http://localhost:8000/health > /dev/null 2>&1; do
        sleep 0.5
        COUNT=$((COUNT + 1))
        if [ $COUNT -ge 30 ]; then
            echo "Warning: FastAPI health check timed out. Proceeding to launch dashboard..."
            break
        fi
    done
    echo "FastAPI is active!"

    echo "Starting Streamlit Dashboard on port 8501..."
    exec streamlit run dashboard/app.py \
        --server.port=8501 \
        --server.address=0.0.0.0 \
        --server.headless=true \
        --browser.gatherUsageStats=false
fi
