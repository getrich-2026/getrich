#!/bin/bash
# run_pipeline.sh - Robust wrapper to run and resume yinhe_data_fetcher until completion

LOG_FILE="./logs/yinhe_data_fetcher.log"

# Clear any previous success indicator in the log to ensure clean detection
if [ -f "$LOG_FILE" ]; then
    # We remove any previous success messages so we don't false-positive match them
    sed -i '/all fetchers finished/d' "$LOG_FILE"
fi

while true; do
    echo "[$(date)] Starting yinhe_data_fetcher in update mode..."
    uv run python main.py update
    exit_code=$?
    echo "[$(date)] yinhe_data_fetcher exited with code $exit_code"
    
    # Check if the log contains the completion message written at the end of a successful run
    if grep -q "all fetchers finished" "$LOG_FILE"; then
        echo "[$(date)] Ingestion pipeline completed successfully!"
        break
    else
        echo "[$(date)] Pipeline was interrupted or did not finish. Restarting in 5 seconds..."
        sleep 5
    fi
done
