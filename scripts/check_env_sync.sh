#!/usr/bin/env bash
set -euo pipefail

# Environment sync/fingerprint helper for SkiCycleRun pipeline.
# Modes:
#  - default: audit pinned requirements + critical import check
#  - --apply: install/upgrade mismatched pinned requirements
#  - --fingerprint: write machine/env fingerprint to file
#  - --compare FILE_A FILE_B: compare two fingerprint files

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REQ_FILE="$ROOT_DIR/requirements.txt"
APPLY_FIX=0
DO_FINGERPRINT=0
DO_COMPARE=0
COMPARE_A=""
COMPARE_B=""
FINGERPRINT_OUT=""
PYTHON_CMD=""

usage() {
  cat <<'EOF'
Usage:
  ./scripts/check_env_sync.sh [--python /path/to/python] [--apply]
  ./scripts/check_env_sync.sh [--python /path/to/python] --fingerprint [--out FILE]
  ./scripts/check_env_sync.sh --compare FILE_A FILE_B

Options:
  --apply             Install/upgrade packages to match pinned versions in requirements.txt
  --fingerprint       Write a full machine + Python + ML stack fingerprint
  --out FILE          Output path for --fingerprint
  --compare A B       Compare two previously generated fingerprint files
  --python PATH       Python interpreter to use (defaults: python3, then python)
  -h, --help          Show help

Examples:
  ./scripts/check_env_sync.sh
  ./scripts/check_env_sync.sh --apply
  ./scripts/check_env_sync.sh --fingerprint
  ./scripts/check_env_sync.sh --fingerprint --out logs/mbp.fingerprint.txt
  ./scripts/check_env_sync.sh --compare logs/mbp.fingerprint.txt logs/macmini.fingerprint.txt
EOF
}

resolve_python() {
  if [[ -n "$PYTHON_CMD" ]]; then
    if [[ ! -x "$PYTHON_CMD" ]]; then
      echo "ERROR: specified python is not executable: $PYTHON_CMD" >&2
      exit 1
    fi
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="$(command -v python3)"
  elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD="$(command -v python)"
  else
    echo "ERROR: neither python3 nor python found in PATH" >&2
    exit 1
  fi
}

print_header() {
  echo "=== SkiCycleRun Environment Tool ==="
  echo "Project root: $ROOT_DIR"
  echo "Requirements: $REQ_FILE"
  echo "Python: $PYTHON_CMD"
  echo
}

write_fingerprint() {
  local out_file="$1"
  mkdir -p "$(dirname "$out_file")"

  {
    echo "# SkiCycleRun Fingerprint"
    echo "timestamp_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "hostname=$(hostname)"
    echo "project_root=$ROOT_DIR"
    echo
    echo "[system]"
    sw_vers 2>/dev/null || true
    sysctl -n machdep.cpu.brand_string 2>/dev/null | sed 's/^/cpu_brand=/' || true
    sysctl -n hw.memsize 2>/dev/null | awk '{printf "mem_bytes=%s\n", $1}' || true
    system_profiler SPHardwareDataType 2>/dev/null | grep -E 'Model Name|Model Identifier|Chip|Total Number of Cores|Memory' || true
    echo
    echo "[python]"
    echo "python_executable=$PYTHON_CMD"
    "$PYTHON_CMD" --version 2>&1 | sed 's/^/python_version=/'
    "$PYTHON_CMD" -m pip --version 2>&1 | sed 's/^/pip_version=/' || true
    echo
    echo "[ml_packages]"
    "$PYTHON_CMD" - <<'PY'
import importlib
pkgs = ["torch", "torchvision", "torchaudio", "diffusers", "transformers", "accelerate", "peft", "safetensors", "tokenizers", "numpy"]
for name in pkgs:
    try:
        m = importlib.import_module(name)
        print(f"{name}={getattr(m, '__version__', 'unknown')}")
    except Exception as e:
        print(f"{name}=MISSING ({type(e).__name__}: {e})")
PY
    echo
    echo "[torch_runtime]"
    "$PYTHON_CMD" - <<'PY'
try:
    import torch
    print(f"torch_version={torch.__version__}")
    print(f"cuda_available={torch.cuda.is_available()}")
    print(f"mps_built={torch.backends.mps.is_built()}")
    print(f"mps_available={torch.backends.mps.is_available()}")
except Exception as e:
    print(f"torch_runtime_error={type(e).__name__}: {e}")
PY
    echo
    echo "[critical_import]"
    "$PYTHON_CMD" - <<'PY'
try:
    import diffusers
    print(f"diffusers_version={diffusers.__version__}")
    print(f"diffusers_file={diffusers.__file__}")
    from diffusers import FluxKontextPipeline  # noqa: F401
    print("FluxKontextPipeline=OK")
except Exception as e:
    print(f"FluxKontextPipeline=FAIL ({type(e).__name__}: {e})")
PY
    echo
    echo "[pip_freeze]"
    "$PYTHON_CMD" -m pip freeze 2>/dev/null || true
  } > "$out_file"

  echo "Fingerprint written: $out_file"
}

compare_fingerprints() {
  local a="$1"
  local b="$2"
  if [[ ! -f "$a" || ! -f "$b" ]]; then
    echo "ERROR: both files must exist for compare" >&2
    echo "A: $a" >&2
    echo "B: $b" >&2
    exit 1
  fi

  echo "=== Fingerprint Compare ==="
  echo "A: $a"
  echo "B: $b"
  echo

  local keys='python_version|python_executable|pip_version|torch=|torchvision=|torchaudio=|diffusers=|transformers=|accelerate=|peft=|numpy=|mps_available=|cuda_available=|FluxKontextPipeline='
  echo "[Key Differences]"
  diff -u <(grep -E "$keys" "$a" | sort) <(grep -E "$keys" "$b" | sort) || true
  echo
  echo "[Hint] Full diff (optional): diff -u \"$a\" \"$b\""
}

run_audit_sync() {
  if [[ ! -f "$REQ_FILE" ]]; then
    echo "ERROR: requirements file not found at $REQ_FILE" >&2
    exit 1
  fi

  print_header

  echo "[Python]"
  echo "Executable: $PYTHON_CMD"
  "$PYTHON_CMD" --version
  "$PYTHON_CMD" -m pip --version || true
  echo

  echo "[Core Import Check]"
  "$PYTHON_CMD" - <<'PY'
try:
    import diffusers
    print(f"diffusers version: {diffusers.__version__}")
    print(f"diffusers file: {diffusers.__file__}")
    from diffusers import FluxKontextPipeline  # noqa: F401
    print("FluxKontextPipeline import: OK")
except Exception as e:
    print(f"FluxKontextPipeline import: FAIL ({type(e).__name__}: {e})")
PY
  echo

  echo "[Pinned Package Sync Check]"
  PINS=()
  while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
    line="${raw_line%%#*}"
    line="${line//[[:space:]]/}"
    [[ -z "$line" ]] && continue
    if [[ "$line" == *"=="* ]]; then
      PINS+=("$line")
    fi
  done < "$REQ_FILE"

  if [[ ${#PINS[@]} -eq 0 ]]; then
    echo "No pinned packages found in requirements.txt"
    exit 0
  fi

  MISMATCHES=()
  for pin in "${PINS[@]}"; do
    pkg="${pin%%==*}"
    want="${pin##*==}"

    if "$PYTHON_CMD" -m pip show "$pkg" >/dev/null 2>&1; then
      have="$("$PYTHON_CMD" - "$pkg" <<'PY'
import importlib.metadata
import sys

name = sys.argv[1]
try:
    print(importlib.metadata.version(name))
except importlib.metadata.PackageNotFoundError:
    pass
PY
)"
      if [[ "$have" == "$want" ]]; then
        printf 'OK   %-20s installed=%-12s required=%s\n' "$pkg" "$have" "$want"
      else
        printf 'DIFF %-20s installed=%-12s required=%s\n' "$pkg" "$have" "$want"
        MISMATCHES+=("$pin")
      fi
    else
      printf 'MISS %-20s installed=%-12s required=%s\n' "$pkg" "(not installed)" "$want"
      MISMATCHES+=("$pin")
    fi
  done

  echo
  if [[ ${#MISMATCHES[@]} -eq 0 ]]; then
    echo "All pinned packages are in sync."
    exit 0
  fi

  echo "Found ${#MISMATCHES[@]} mismatched/missing pinned package(s)."
  printf '  - %s\n' "${MISMATCHES[@]}"

  if [[ $APPLY_FIX -eq 1 ]]; then
    echo
    echo "[Applying Fixes] Installing pinned versions..."
    "$PYTHON_CMD" -m pip install "${MISMATCHES[@]}"
    echo "Re-running quick verification..."
    "$PYTHON_CMD" - <<'PY'
try:
    from diffusers import FluxKontextPipeline  # noqa: F401
    print("FluxKontextPipeline import after fix: OK")
except Exception as e:
    print(f"FluxKontextPipeline import after fix: FAIL ({type(e).__name__}: {e})")
    raise
PY
    echo "Done."
  else
    echo "Run with --apply to auto-install pinned versions."
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --apply)
      APPLY_FIX=1
      shift
      ;;
    --fingerprint)
      DO_FINGERPRINT=1
      shift
      ;;
    --out)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --out requires a file path" >&2
        exit 2
      fi
      FINGERPRINT_OUT="$2"
      shift 2
      ;;
    --compare)
      if [[ $# -lt 3 ]]; then
        echo "ERROR: --compare requires two files" >&2
        exit 2
      fi
      DO_COMPARE=1
      COMPARE_A="$2"
      COMPARE_B="$3"
      shift 3
      ;;
    --python)
      if [[ $# -lt 2 ]]; then
        echo "ERROR: --python requires a path" >&2
        exit 2
      fi
      PYTHON_CMD="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

resolve_python

if [[ $DO_COMPARE -eq 1 ]]; then
  compare_fingerprints "$COMPARE_A" "$COMPARE_B"
  exit 0
fi

if [[ $DO_FINGERPRINT -eq 1 ]]; then
  if [[ -z "$FINGERPRINT_OUT" ]]; then
    ts="$(date -u +%Y%m%dT%H%M%SZ)"
    FINGERPRINT_OUT="$ROOT_DIR/logs/fingerprint_${ts}.txt"
  fi
  write_fingerprint "$FINGERPRINT_OUT"
  exit 0
fi

run_audit_sync
