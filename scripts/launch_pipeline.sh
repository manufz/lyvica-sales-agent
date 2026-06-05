#!/bin/bash
# Fire-and-forget pipeline launcher for interactive (Telegram) requests.
#
# Usage:  launch_pipeline.sh "<city>" "<industry>" [limit]
#
# Starts run_pipeline.py detached and returns immediately so the Hermes agent
# loop never blocks on the multi-minute scoring run. The background job posts
# its results to Telegram when finished (same delivery as the daily cron).

CITY="${1:?usage: launch_pipeline.sh <city> <industry> [limit]}"
INDUSTRY="${2:?usage: launch_pipeline.sh <city> <industry> [limit]}"
LIMIT="${3:-10}"

DIR="/Users/macpro/work/lyvica-sales-agent"
PY="$DIR/.venv/bin/python"
LOG="/Users/macpro/logs/pipeline.log"

nohup "$PY" "$DIR/scripts/run_pipeline.py" \
    --city "$CITY" --industry "$INDUSTRY" --limit "$LIMIT" \
    >> "$LOG" 2>&1 &

echo "started pipeline for $INDUSTRY in $CITY (limit $LIMIT) — results will post to Telegram in a few minutes"
