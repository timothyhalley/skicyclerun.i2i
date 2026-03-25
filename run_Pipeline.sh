#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

printf '🚀 Starting pipeline in caffeinated mode\n'
printf '📋 Command: python3 pipeline.py'
for arg in "$@"; do
  printf ' %q' "$arg"
done
printf '\n'

if command -v caffeinate >/dev/null 2>&1; then
  exec caffeinate -dimsu python3 pipeline.py "$@"
else
  printf '⚠️  caffeinate not found; running without sleep prevention\n'
  exec python3 pipeline.py "$@"
fi
