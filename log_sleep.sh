#!/usr/bin/env bash
# Overnight sleep HR logger for the rabota pipeline (Sprint A1).
#
# Wraps sleep_logger.py in `caffeinate` so the Mac (and its Bluetooth radio)
# stays awake all night with the lid open or display asleep. Keep the Mac
# plugged in.
#
# Usage:
#   ./log_sleep.sh                       # match any device named "Forerunner"
#   ./log_sleep.sh --address <UUID>      # target your watch directly (most reliable)
#   ./log_sleep.sh --name Forerunner     # match by name substring
#
# Any flags you pass are forwarded straight to sleep_logger.py.
# Stop with Ctrl+C in the morning; data is flushed on every reading.
set -euo pipefail

cd "$(dirname "$0")"

# Default to matching the Forerunner by name if no target flag was given.
args=("$@")
if [[ $# -eq 0 ]]; then
  args=(--name Forerunner)
fi

# caffeinate flags: -i no idle sleep, -m no disk sleep, -s no system sleep
# (on AC), -d no display sleep. Runs sleep_logger.py as its child.
exec caffeinate -imsd .venv/bin/python sleep_logger.py "${args[@]}"
