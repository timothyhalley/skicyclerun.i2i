#!/usr/bin/env bash
# shellcheck shell=bash
set -uo pipefail

# Environment profile switcher for SkiCycleRun pipeline.
# Activates or rebuilds a named machine profile venv without touching
# any other venv on the system. Your fast Mini stays fast.
#
# Profiles live in constraints/ and are named by machine + date.
#
# Usage (direct — build/verify only):
#   ./scripts/switch_env_profile.sh --list
#   ./scripts/switch_env_profile.sh --status
#   ./scripts/switch_env_profile.sh --rebuild mini
#
# Usage (activate in current shell — pipe through source):
#   source <(./scripts/switch_env_profile.sh mini)
#   source <(./scripts/switch_env_profile.sh mbp)

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONSTRAINTS_DIR="$ROOT_DIR/constraints"

REBUILD=0
ACTION=""
PROFILE=""

# ── Profile registry ──────────────────────────────────────────────────────────
# macOS bash 3.2 does not support associative arrays (declare -A).
# Add a new case arm in each function below when adding a new profile.

KNOWN_PROFILES="mini mbp"

profile_file() {
  case "$1" in
    mini) echo "macmini-fast-20260326.txt" ;;
    mbp)  echo "mbp-repro-20260326.txt" ;;
    *)    echo "" ;;
  esac
}

profile_venv() {
  case "$1" in
    mini) echo ".venv-mini-fast" ;;
    mbp)  echo ".venv-mbp-repro" ;;
    *)    echo "" ;;
  esac
}

profile_desc() {
  case "$1" in
    mini) echo "Mac mini M4 Pro — torch 2.7 / diffusers dev / fast stack" ;;
    mbp)  echo "MacBook Pro M5 — torch 2.8 / diffusers 0.35.2" ;;
    *)    echo "" ;;
  esac
}
# ─────────────────────────────────────────────────────────────────────────────


usage() {
  cat <<'EOF'
Usage:
  ./scripts/switch_env_profile.sh <profile>           Activate (or create) profile venv
  ./scripts/switch_env_profile.sh --rebuild <profile> Force-rebuild venv from scratch
  ./scripts/switch_env_profile.sh --list              Show available profiles
  ./scripts/switch_env_profile.sh --status            Show current venv + key package versions
  ./scripts/switch_env_profile.sh -h | --help         Show this help

Profiles:
  mini    Mac mini M4 Pro fast stack  (torch 2.7 / diffusers dev)
  mbp     MacBook Pro M5 repro stack  (torch 2.8 / diffusers 0.35.2)

Examples:
  source <(./scripts/switch_env_profile.sh mini)    Activate mini venv in current shell
  ./scripts/switch_env_profile.sh --rebuild mbp     Nuke + rebuild MBP venv
  ./scripts/switch_env_profile.sh --status          Check what is active
EOF
}

list_profiles() {
  echo "=== Available Environment Profiles ==="
  echo ""
  for alias in $KNOWN_PROFILES; do
    local file venv desc state venv_path
    file="$(profile_file "$alias")"
    venv="$(profile_venv "$alias")"
    desc="$(profile_desc "$alias")"
    venv_path="$ROOT_DIR/$venv"
    if [[ -d "$venv_path" ]]; then
      state="✅ venv exists"
    else
      state="⬜ not yet built"
    fi
    printf "  %-8s  %s\n" "$alias" "$desc"
    printf "           constraints: %s\n" "$file"
    printf "           venv dir:    %s  [%s]\n\n" "$venv" "$state"
  done
}

show_status() {
  echo "=== Current Python Environment ==="
  local python_cmd
  if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    python_cmd="$VIRTUAL_ENV/bin/python"
  else
    python_cmd="$(command -v python3 2>/dev/null || command -v python 2>/dev/null || echo "")"
  fi
  if [[ -z "$python_cmd" ]]; then
    echo "ERROR: No python found in PATH." >&2
    exit 1
  fi
  echo "VIRTUAL_ENV : ${VIRTUAL_ENV:-(none — no venv active)}"
  echo "Python      : $python_cmd"
  "$python_cmd" --version 2>&1
  echo ""
  echo "[Key ML packages]"
  "$python_cmd" - <<'PY'
import importlib
for name in ["torch", "torchvision", "torchaudio", "diffusers", "accelerate", "peft", "transformers", "numpy"]:
    try:
        m = importlib.import_module(name)
        print(f"  {name:<16} {getattr(m, '__version__', 'unknown')}")
    except Exception as e:
        print(f"  {name:<16} MISSING")
PY
}

build_venv() {
  local alias="$1"
  local constraints_file="$CONSTRAINTS_DIR/$(profile_file "$alias")"
  local venv_dir="$ROOT_DIR/$(profile_venv "$alias")"

  if [[ ! -f "$constraints_file" ]]; then
    echo "ERROR: Constraints file not found: $constraints_file" >&2
    exit 1
  fi

  if [[ $REBUILD -eq 1 && -d "$venv_dir" ]]; then
    echo "🗑️  Removing existing venv: $venv_dir"
    rm -rf "$venv_dir"
  fi

  if [[ ! -d "$venv_dir" ]]; then
    echo "🔧 Creating venv: $venv_dir"
    python3 -m venv "$venv_dir"
  fi

  echo "📦 Installing profile: $alias"
  echo "   Description : $(profile_desc "$alias")"
  echo "   Constraints : $constraints_file"
  echo ""
  "$venv_dir/bin/pip" install --upgrade pip --quiet
  "$venv_dir/bin/pip" install -r "$constraints_file"
  echo ""
  echo "✅ Profile '$alias' is ready."
}

emit_activate() {
  local alias="$1"
  local venv_dir="$ROOT_DIR/$(profile_venv "$alias")"
  local desc
  desc="$(profile_desc "$alias")"

  if [[ ! -d "$venv_dir" ]]; then
    echo "⬜ Venv for '$alias' does not exist yet — building first..." >&2
    build_venv "$alias"
  fi

  # Emit the activate command so the caller's shell picks it up when using:
  #   source <(./scripts/switch_env_profile.sh mini)
  echo "source \"$venv_dir/bin/activate\""
  echo "echo '✅ Activated: $alias — $desc'"
}

# ── Argument parsing ──────────────────────────────────────────────────────────
if [[ $# -eq 0 ]]; then
  usage
  exit 0
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage; exit 0 ;;
    --list)
      list_profiles; exit 0 ;;
    --status)
      show_status; exit 0 ;;
    --rebuild)
      REBUILD=1
      shift
      if [[ $# -eq 0 ]]; then
        echo "ERROR: --rebuild requires a profile name (mini or mbp)" >&2
        exit 1
      fi
      PROFILE="$1"; ACTION="rebuild"; shift ;;
    mini|mbp)
      PROFILE="$1"; ACTION="activate"; shift ;;
    *)
      echo "ERROR: Unknown argument: $1" >&2
      echo "Run with --help for usage." >&2
      exit 1 ;;
  esac
done

# ── Validate profile ──────────────────────────────────────────────────────────
if [[ -n "$PROFILE" ]] && [[ -z "$(profile_file "$PROFILE")" ]]; then
  echo "ERROR: Unknown profile '$PROFILE'. Known profiles: $KNOWN_PROFILES" >&2
  exit 1
fi

# ── Dispatch ──────────────────────────────────────────────────────────────────
case "$ACTION" in
  activate)
    emit_activate "$PROFILE"
    ;;
  rebuild)
    build_venv "$PROFILE"
    echo ""
    echo "To activate, run:"
    echo "  source <(./scripts/switch_env_profile.sh $PROFILE)"
    ;;
esac
