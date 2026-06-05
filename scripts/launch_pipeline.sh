#!/bin/bash
# Fire-and-forget pipeline launcher for interactive (Telegram) requests.
#
# Usage:
#   launch_pipeline.sh "<city>" "<industry>" [limit]   # specific market
#   launch_pipeline.sh                                  # auto-select by yield
#
# Starts run_pipeline.py detached and returns immediately so the Hermes agent
# loop never blocks on the multi-minute scoring run. The background job posts
# its results to Telegram when finished (same delivery as the daily cron).

CITY="$1"
INDUSTRY="$2"
LIMIT="${3:-10}"

DIR="/Users/macpro/work/lyvica-sales-agent"
PY="$DIR/.venv/bin/python"
LOG="/Users/macpro/logs/pipeline.log"

if [ -n "$CITY" ] && [ -n "$INDUSTRY" ]; then
    nohup "$PY" "$DIR/scripts/run_pipeline.py" \
        --city "$CITY" --industry "$INDUSTRY" --limit "$LIMIT" >> "$LOG" 2>&1 &
    echo "started pipeline for $INDUSTRY in $CITY (limit $LIMIT) — results post to Telegram in a few minutes"
else
    # No market specified → the pipeline's yield-aware selector picks the next one
    nohup "$PY" "$DIR/scripts/run_pipeline.py" --limit "$LIMIT" >> "$LOG" 2>&1 &
    echo "started pipeline for the auto-selected next market (by yield) — results post to Telegram in a few minutes"
fi
