#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ "$#" -eq 0 ]; then
  printf '🧭 No arguments provided. Showing setup help.\n\n'
  printf 'Quick start:\n'
  printf '  ./run_SetupEnv.sh --profile performance/macmini-fast-20260326.txt\n'
  printf '  ./run_SetupEnv.sh --profile performance/mbp-repro-20260326.txt\n'
  printf '  ./run_SetupEnv.sh --profile performance/macmini-fast-20260326.txt --capture-only\n\n'
  exec python3 scripts/env_setup.py --help
fi

printf '🧰 Running environment setup\n'
printf '📋 Command: python3 scripts/env_setup.py'
for arg in "$@"; do
  printf ' %q' "$arg"
done
printf '\n'

exec python3 scripts/env_setup.py "$@"
