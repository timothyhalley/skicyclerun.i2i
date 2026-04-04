#!/usr/bin/env python3
"""
env_setup.py — SkiCycleRun one-shot environment bootstrapper.

Reads a performance profile file, then performs every setup step in one go:
  1. Sets the correct Python version via pyenv (global + .python-version)
  2. Regenerates requirements.txt from the profile's package list
  3. Runs pip install -r requirements.txt
  4. Writes .env with all runtime paths and MPS/PyTorch performance flags
     → pipeline.py loads .env automatically on every startup
  5. Updates config/pipeline_config.json defaults and records setup provenance
  6. Validates MPS (Apple GPU) availability — loud warning if falling back to CPU

After running this ONCE, any new shell can go straight to:
  ./run_Pipeline.sh [--stages lora_processing ...]
No sourcing, no preamble, no manual env vars.

Usage:
    python3 scripts/env_setup.py --profile performance/macmini-fast-20260326.txt
    python3 scripts/env_setup.py --profile performance/mbp-repro-20260326.txt

  # Override paths for a different drive mount:
    python3 scripts/env_setup.py --profile performance/macmini-fast-20260326.txt \\
      --lib-root  /Volumes/MySSD/skicyclerun.i2i \\
      --hf-cache  /Volumes/MySSD/huggingface

  # Dry-run: update .env and config only, skip pip install:
    python3 scripts/env_setup.py --profile performance/macmini-fast-20260326.txt --skip-install
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from importlib import metadata as importlib_metadata
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

PROJECT_ROOT        = Path(__file__).resolve().parent.parent
PERFORMANCE_DIR     = PROJECT_ROOT / "performance"
CONFIG_PATH         = PROJECT_ROOT / "config" / "pipeline_config.json"
REQUIREMENTS_PATH   = PROJECT_ROOT / "requirements.txt"
ENV_FILE_PATH       = PROJECT_ROOT / ".env"
PYTHON_VERSION_FILE = PROJECT_ROOT / ".python-version"

# Metadata keys recognised inside profile comment lines  (# key: value)
META_KEYS = {
    "python_version",
    "lib_root",
    "huggingface_cache",
    "device",
    "precision",
    "num_inference_steps",
    "guidance_scale",
    "pytorch_mps_high_watermark_ratio",
    "pytorch_mps_low_watermark_ratio",
    "pytorch_enable_mps_fallback",
    "tokenizers_parallelism",
    "omp_num_threads",
    "torch_matmul_precision",
    "torch_compile",
    "torch_compile_backend",
    "torch_compile_mode",
    "torch_compile_on_mps",
    "torch_compile_allow_mps_inductor",
}

# ── Console helpers ───────────────────────────────────────────────────────────

def banner(title: str) -> None:
    width = 70
    print(f"\n{'═' * width}")
    print(f"  {title}")
    print(f"{'═' * width}")

def step(title: str) -> None:
    print(f"\n📌 {title}")

def ok(msg: str)   -> None: print(f"  ✅ {msg}")
def warn(msg: str) -> None: print(f"  ⚠️  {msg}")
def fail(msg: str) -> None: print(f"  ❌ {msg}")
def info(msg: str) -> None: print(f"  ℹ️  {msg}")

def _run(cmd: List[str], *, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    if capture:
        return subprocess.run(cmd, check=check, capture_output=True, text=True)
    return subprocess.run(cmd, check=check)


def _safe_machine_name() -> str:
    host = os.uname().nodename if hasattr(os, "uname") else "machine"
    # Keep filenames portable and predictable.
    return re.sub(r"[^A-Za-z0-9._-]+", "-", host).strip("-") or "machine"


def _get_pyenv_global_version() -> str:
    if not shutil.which("pyenv"):
        return "(pyenv not found)"
    result = _run(["pyenv", "global"], capture=True, check=False)
    if result.returncode != 0:
        return "(unknown)"
    return result.stdout.strip() or "(unknown)"


def _get_pyenv_python_executable() -> str | None:
    """Return the active pyenv Python executable for the current project."""
    if not shutil.which("pyenv"):
        return None

    for candidate in ("python3", "python"):
        result = _run(["pyenv", "which", candidate], capture=True, check=False)
        if result.returncode == 0:
            resolved = result.stdout.strip()
            if resolved:
                return resolved
    return None


def _normalize_executable(path_str: str | None) -> str:
    if not path_str:
        return ""
    try:
        return str(Path(path_str).resolve())
    except OSError:
        return path_str


def maybe_reexec_with_pyenv_python(*, skip_pyenv: bool, reexeced: bool) -> None:
    """Re-enter the setup script under the pinned pyenv interpreter if needed."""
    if skip_pyenv or reexeced:
        return

    target_python = _get_pyenv_python_executable()
    if not target_python:
        return

    current_python = _normalize_executable(sys.executable)
    target_python = _normalize_executable(target_python)
    if current_python == target_python:
        return

    step("Switching setup into the pinned pyenv interpreter")
    info(f"Current interpreter: {current_python}")
    info(f"Pinned interpreter:  {target_python}")

    reexec_args = [target_python, str(Path(__file__).resolve()), *sys.argv[1:]]
    if "--skip-snapshot" not in sys.argv[1:]:
        reexec_args.append("--skip-snapshot")
    reexec_args.append("--reexeced")
    os.execv(target_python, reexec_args)


def write_prechange_snapshot(profile_name: str) -> None:
    """Persist rollback-friendly snapshot before env setup mutates state."""
    step("Saving pre-change environment snapshot")

    PERFORMANCE_DIR.mkdir(parents=True, exist_ok=True)

    machine = _safe_machine_name()
    ts_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ts_file = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    snapshot_path = PERFORMANCE_DIR / f"current-{machine}-{ts_file}.txt"
    latest_path = PERFORMANCE_DIR / f"current-{machine}.txt"

    current_requirements = ""
    if REQUIREMENTS_PATH.exists():
        current_requirements = REQUIREMENTS_PATH.read_text().rstrip() + "\n"

    pip_freeze = ""
    freeze = _run([sys.executable, "-m", "pip", "freeze"], capture=True, check=False)
    if freeze.returncode == 0:
        pip_freeze = freeze.stdout.rstrip() + "\n"
    else:
        pip_freeze = "# pip freeze unavailable in current interpreter\n"

    active_python_version = sys.version.split()[0]
    pinned_python_version = PYTHON_VERSION_FILE.read_text().strip() if PYTHON_VERSION_FILE.exists() else "(missing .python-version)"
    pyenv_global = _get_pyenv_global_version()

    content = (
        f"# SkiCycleRun Current Environment Snapshot\n"
        f"# Captured: {ts_iso}\n"
        f"# Machine: {machine}\n"
        f"# Triggered by: scripts/env_setup.py\n"
        f"# Profile being applied next: performance/{profile_name}\n"
        f"\n"
        f"# python_runtime_version: {active_python_version}\n"
        f"# python_runtime_executable: {sys.executable}\n"
        f"# python_version_file: {pinned_python_version}\n"
        f"# pyenv_global: {pyenv_global}\n"
        f"\n"
        f"# --- BEGIN requirements.txt (pre-change) ---\n"
        f"{current_requirements if current_requirements else '# requirements.txt missing before run\\n'}"
        f"# --- END requirements.txt (pre-change) ---\n"
        f"\n"
        f"# --- BEGIN pip freeze (pre-change) ---\n"
        f"{pip_freeze}"
        f"# --- END pip freeze (pre-change) ---\n"
    )

    snapshot_path.write_text(content)
    latest_path.write_text(content)
    ok(f"Snapshot saved: {snapshot_path}")
    ok(f"Latest snapshot: {latest_path}")


def _infer_profile_name_from_config() -> str:
    """Best-effort profile name when capture-only is run without --profile."""
    if not CONFIG_PATH.exists():
        return "snapshot-only"

    try:
        cfg = json.loads(CONFIG_PATH.read_text())
        profile_val = ((cfg.get("python_environment") or {}).get("profile") or "").strip()
        if profile_val:
            return Path(profile_val).name
    except Exception:
        pass
    return "snapshot-only"


def _parse_requirement_line(line: str) -> Tuple[str | None, str | None]:
    """Return (normalized_name, spec) for a requirement line."""
    cleaned = line.strip()
    if not cleaned or cleaned.startswith("#"):
        return None, None

    if " @ " in cleaned:
        name, _, ref = cleaned.partition(" @ ")
        return name.strip().lower(), f"@ {ref.strip()}"

    m = re.match(r"^([A-Za-z0-9_.-]+)\s*(.*)$", cleaned)
    if not m:
        return None, None

    name = m.group(1).strip().lower()
    spec = m.group(2).strip() if m.group(2) else "(any)"
    return name, spec or "(any)"


def _get_installed_version(dist_name: str) -> str:
    try:
        return importlib_metadata.version(dist_name)
    except importlib_metadata.PackageNotFoundError:
        # Pillow's distribution is often registered as "Pillow".
        if dist_name.lower() == "pillow":
            try:
                return importlib_metadata.version("Pillow")
            except importlib_metadata.PackageNotFoundError:
                return "(not installed)"
        return "(not installed)"


def print_change_summary(packages: List[str], profile_name: str) -> None:
    """Print what key package versions will change before applying profile."""
    step("Planned dependency changes (pre-apply)")
    print(f"  🧾 Target profile: performance/{profile_name}")

    target_specs: Dict[str, str] = {}
    for line in packages:
        pkg_name, pkg_spec = _parse_requirement_line(line)
        if pkg_name:
            target_specs[pkg_name] = pkg_spec or "(any)"

    key_dists = [
        "torch", "torchvision", "diffusers", "transformers", "accelerate",
        "peft", "safetensors", "tokenizers", "numpy", "pillow", "psutil",
    ]

    for dist in key_dists:
        current = _get_installed_version(dist)
        target = target_specs.get(dist, "(not specified)")

        if target == "(not specified)":
            status = "⚪ no profile pin"
            detail = f"installed={current}"
        elif target.startswith("=="):
            target_ver = target[2:].strip()
            if current == target_ver:
                status = "✅ unchanged"
                detail = f"{current}"
            else:
                status = "🔁 will change"
                detail = f"{current} -> {target_ver}"
        elif target.startswith("@"):
            status = "🔁 source override"
            detail = f"{current} -> {target}"
        else:
            status = "🔧 constrained"
            detail = f"installed={current}, target={target}"

        print(f"  {status:<17} {dist:<12} {detail}")

# ── Profile parsing ───────────────────────────────────────────────────────────

def parse_profile(path: Path) -> Tuple[Dict[str, str], List[str]]:
    """
    Parse a performance profile file.

    Lines of the form  '# key: value'  where key is in META_KEYS are treated
    as machine-specific metadata.  All other non-blank, non-comment lines are
    treated as pip requirement specs.

    Returns:
        metadata  — dict of key → value
        packages  — list of pip requirement lines
    """
    metadata: Dict[str, str] = {}
    packages: List[str] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            m = re.match(r"^#\s*([a-z_]+)\s*:\s*(.+)$", line, re.IGNORECASE)
            if m and m.group(1).lower() in META_KEYS:
                metadata[m.group(1).lower()] = m.group(2).strip()
        else:
            packages.append(line)
    return metadata, packages

# ── pyenv ─────────────────────────────────────────────────────────────────────

def set_pyenv_version(version: str) -> None:
    step(f"Python version → {version} (via pyenv)")

    if not shutil.which("pyenv"):
        warn("pyenv not found in PATH — skipping Python version management.")
        warn("Install pyenv: https://github.com/pyenv/pyenv")
        return

    result = _run(["pyenv", "versions", "--bare"], capture=True, check=False)
    installed = [v.strip().lstrip("* ") for v in result.stdout.splitlines()] if result.returncode == 0 else []

    if version not in installed:
        print(f"  📦 Python {version} not installed — running pyenv install (may take a few minutes)...")
        _run(["pyenv", "install", version])
        ok(f"Python {version} installed")
    else:
        ok(f"Python {version} already installed")

    _run(["pyenv", "global", version])
    ok(f"pyenv global → {version}")

    PYTHON_VERSION_FILE.write_text(version + "\n")
    ok(f".python-version → {version}")

# ── requirements.txt ──────────────────────────────────────────────────────────

def build_requirements(packages: List[str], profile_name: str) -> None:
    step(f"Regenerating requirements.txt from profile: {profile_name}")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    header = (
        f"# Generated by:  python3 scripts/env_setup.py --profile performance/{profile_name}\n"
        f"# Last updated:  {ts}\n"
        f"# Source:        performance/{profile_name}\n"
        f"#\n"
        f"# DO NOT EDIT MANUALLY — edit the profile file, then re-run scripts/env_setup.py.\n"
        f"\n"
    )
    REQUIREMENTS_PATH.write_text(header + "\n".join(packages) + "\n")
    ok(f"requirements.txt → {len(packages)} packages")

# ── pip install ───────────────────────────────────────────────────────────────

def install_requirements() -> None:
    step("Upgrading pip")
    _run([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
    ok("pip upgraded")

    step("Installing requirements.txt")
    print("  🚀 First run may take several minutes — installing ML libraries...")
    _run([sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_PATH)])
    ok("All packages installed")

# ── .env ──────────────────────────────────────────────────────────────────────

def write_env_file(lib_root: str, hf_cache: str, meta: Dict[str, str], profile_name: str) -> None:
    step("Writing .env (auto-loaded by pipeline.py on every run)")

    ts       = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    mps_high = meta.get("pytorch_mps_high_watermark_ratio", "0.0")
    mps_low  = meta.get("pytorch_mps_low_watermark_ratio",  "0.7")
    mps_fb   = meta.get("pytorch_enable_mps_fallback",      "1")
    tok_par  = meta.get("tokenizers_parallelism",            "false")
    omp      = meta.get("omp_num_threads",                   "1")
    matmul_precision = meta.get("torch_matmul_precision",     "high")
    torch_compile = meta.get("torch_compile",                 "0")
    torch_compile_backend = meta.get("torch_compile_backend", "aot_eager")
    torch_compile_mode = meta.get("torch_compile_mode",       "reduce-overhead")
    torch_compile_on_mps = meta.get("torch_compile_on_mps",   "0")
    torch_compile_allow_mps_inductor = meta.get("torch_compile_allow_mps_inductor", "0")

    content = f"""\
# .env — SkiCycleRun runtime environment
# Generated by scripts/env_setup.py from profile: {profile_name}
# Last updated: {ts}
#
# pipeline.py auto-loads this file on every startup via os.environ.setdefault().
# DO NOT source this file — and DO NOT EDIT by hand.
# Re-run:  python3 scripts/env_setup.py --profile performance/{profile_name}

# ── Paths ─────────────────────────────────────────────────────────────────────
SKICYCLERUN_LIB_ROOT={lib_root}
HUGGINGFACE_CACHE_LIB={hf_cache}
HF_HOME={hf_cache}
HUGGINGFACE_CACHE={hf_cache}

# ── PyTorch / MPS ─────────────────────────────────────────────────────────────
# PYTORCH_ENABLE_MPS_FALLBACK=1: allows unsupported Metal ops to fall to CPU.
# Required for FLUX on macOS — without this the pipeline aborts mid-run.
PYTORCH_ENABLE_MPS_FALLBACK={mps_fb}

# MPS memory watermarks.
# HIGH=0.0  disables the upper eviction limit (recommended for FLUX — avoids
#           constant cache thrashing on large models).
# LOW=0.7   keeps 70% of unified memory available for the OS and other procs.
PYTORCH_MPS_HIGH_WATERMARK_RATIO={mps_high}
PYTORCH_MPS_LOW_WATERMARK_RATIO={mps_low}

# ── HuggingFace ───────────────────────────────────────────────────────────────
# Prevents tokenizer parallelism deadlocks inside forked subprocesses.
TOKENIZERS_PARALLELISM={tok_par}

# ── CPU threading ─────────────────────────────────────────────────────────────
# Limits OpenMP CPU threads so they don't compete with the MPS GPU work queue.
OMP_NUM_THREADS={omp}

# ── Torch runtime tuning ──────────────────────────────────────────────────────
# Global matmul precision policy used by torch.set_float32_matmul_precision().
SKICYCLERUN_MATMUL_PRECISION={matmul_precision}

# Optional torch.compile() for long batch runs (0=off, 1=on).
# On MPS, runtime code defaults to skipping compile unless
# SKICYCLERUN_TORCH_COMPILE_ON_MPS=1 is explicitly set.
SKICYCLERUN_TORCH_COMPILE={torch_compile}
SKICYCLERUN_TORCH_COMPILE_BACKEND={torch_compile_backend}
SKICYCLERUN_TORCH_COMPILE_MODE={torch_compile_mode}
SKICYCLERUN_TORCH_COMPILE_ON_MPS={torch_compile_on_mps}
SKICYCLERUN_TORCH_COMPILE_ALLOW_MPS_INDUCTOR={torch_compile_allow_mps_inductor}
"""
    ENV_FILE_PATH.write_text(content)
    ok(f".env written → {ENV_FILE_PATH}")
    info("pipeline.py loads .env at startup — no shell sourcing required")

# ── pipeline_config.json ──────────────────────────────────────────────────────

def update_pipeline_config(lib_root: str, hf_cache: str, meta: Dict[str, str], profile_name: str) -> None:
    step("Updating config/pipeline_config.json")
    config = json.loads(CONFIG_PATH.read_text())

    # Preserve the ${VAR:default} override syntax but rebind the embedded default
    # to the correct machine path — so the env var still wins if set, but the
    # hardcoded fallback now points to the right location.
    def _rebind(current: str, value: str) -> str:
        m = re.match(r"^\$\{([A-Za-z_][A-Za-z0-9_]*):.*\}$", current.strip())
        return f"${{{m.group(1)}:{value}}}" if m else current

    paths = config.setdefault("paths", {})
    if "lib_root" in paths:
        paths["lib_root"] = _rebind(paths["lib_root"], lib_root)
    if "huggingface_cache" in paths:
        paths["huggingface_cache"] = _rebind(paths["huggingface_cache"], hf_cache)

    # Sync lora_processing tuning knobs from profile metadata
    lora = config.setdefault("lora_processing", {})
    for key, cast in [
        ("device",               str),
        ("precision",            str),
        ("num_inference_steps",  int),
        ("guidance_scale",       float),
    ]:
        if key in meta:
            lora[key] = cast(meta[key])

    # Record setup provenance so you always know which profile last ran
    config["python_environment"] = {
        "python_version":   meta.get("python_version", PYTHON_VERSION_FILE.read_text().strip() if PYTHON_VERSION_FILE.exists() else ""),
        "profile":          f"performance/{profile_name}",
        "lib_root":         lib_root,
        "huggingface_cache": hf_cache,
        "last_setup":       datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")
    ok("pipeline_config.json updated")

# ── Environment verification ──────────────────────────────────────────────────

def verify_environment(expected_device: str) -> None:
    banner("🔍  ENVIRONMENT VERIFICATION")

    ok(f"Python {sys.version.split()[0]}  →  {sys.executable}")

    # ── torch + MPS ────────────────────────────────────────────────────────────
    try:
        import importlib
        torch = importlib.import_module("torch")
        ok(f"torch {torch.__version__}")

        mps_built     = torch.backends.mps.is_built()
        mps_available = torch.backends.mps.is_available()

        print()
        print(f"  {'🟢' if mps_built     else '🔴'}  MPS compiled into torch:  {mps_built}")
        print(f"  {'🟢' if mps_available else '🔴'}  MPS available (runtime):  {mps_available}")
        print()

        if expected_device == "mps":
            if mps_available:
                ok("🎉  MPS ACTIVE — Apple Silicon GPU acceleration confirmed!")
                try:
                    t = torch.tensor([1.0, 2.0], device="mps")
                    _ = (t * t).sum()
                    ok("MPS tensor smoke-test PASSED")
                except Exception as e:
                    warn(f"MPS tensor smoke-test failed: {e}")
            else:
                print("  ╔══════════════════════════════════════════════════════════════╗")
                print("  ║  🚨🚨  MPS NOT AVAILABLE — PIPELINE WILL USE CPU  🚨🚨      ║")
                print("  ║                                                              ║")
                print("  ║  THIS IS THE PRIMARY CAUSE OF SLOW PERFORMANCE.             ║")
                print("  ║                                                              ║")
                print("  ║  Checklist to enable MPS:                                   ║")
                print("  ║  1. macOS 12.3+  (check: sw_vers)                           ║")
                print("  ║  2. Apple Silicon (M1/M2/M3/M4) — not Intel Mac            ║")
                print("  ║  3. torch must be built WITH MPS support.                   ║")
                print("  ║     The macmini-fast profile uses torch==2.7.0 which has    ║")
                print("  ║     better MPS throughput than 2.8.0 on Apple Silicon.      ║")
                print("  ║  4. Re-run scripts/env_setup.py with macmini-fast profile.  ║")
                print("  ╚══════════════════════════════════════════════════════════════╝")

        # ── MPS env var health check ────────────────────────────────────────────
        print()

        def _env_check(name: str, val: str, expected: str, note: str = "") -> None:
            icon = "✅" if val == expected else "⚠️ "
            print(f"  {icon}  {name:<44} = {val}  {note}")

        _env_check("PYTORCH_ENABLE_MPS_FALLBACK",
                   os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK", "NOT SET"),
                   "1",     "(required for FLUX on macOS)")
        _env_check("PYTORCH_MPS_HIGH_WATERMARK_RATIO",
                   os.environ.get("PYTORCH_MPS_HIGH_WATERMARK_RATIO", "NOT SET"),
                   "0.0",   "(0.0 = no eviction ceiling)")
        _env_check("PYTORCH_MPS_LOW_WATERMARK_RATIO",
                   os.environ.get("PYTORCH_MPS_LOW_WATERMARK_RATIO", "NOT SET"),
                   "0.7",   "(keep 70% for OS)")
        _env_check("TOKENIZERS_PARALLELISM",
                   os.environ.get("TOKENIZERS_PARALLELISM", "NOT SET"),
                   "false", "(prevent subprocess deadlocks)")
        _env_check("OMP_NUM_THREADS",
                   os.environ.get("OMP_NUM_THREADS", "NOT SET"),
                   "1",     "(CPU doesn't compete with GPU)")

    except ImportError as e:
        fail(f"torch not importable: {e}")

    # ── package versions ────────────────────────────────────────────────────────
    print()
    for pkg, import_as in [
        ("diffusers",    "diffusers"),
        ("transformers", "transformers"),
        ("peft",         "peft"),
        ("accelerate",   "accelerate"),
        ("safetensors",  "safetensors"),
        ("PIL",          "PIL"),          # installed as pillow
        ("requests",     "requests"),
        ("psutil",       "psutil"),
    ]:
        try:
            m = __import__(import_as)
            ver = getattr(m, "__version__", "ok")
            ok(f"{pkg:<20} {ver}")
        except ImportError:
            fail(f"{pkg} not importable")

    # ── path checks ────────────────────────────────────────────────────────────
    print()
    for label, key in [("SKICYCLERUN_LIB_ROOT", "SKICYCLERUN_LIB_ROOT"),
                       ("HF_HOME",              "HF_HOME")]:
        val = os.environ.get(key, "")
        if val and Path(val).exists():
            ok(f"{label} exists: {val}")
        elif val:
            warn(f"{label}={val}  (directory not found — mount the drive or update the path)")
        else:
            warn(f"{label} not set — will be loaded from .env at pipeline startup")

# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="SkiCycleRun environment bootstrapper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--profile", required=False,
        help="Performance profile file, e.g. performance/macmini-fast-20260326.txt")
    parser.add_argument("--lib-root", default=None,
        help="Override lib_root (pipeline data directory on external drive)")
    parser.add_argument("--hf-cache", default=None,
        help="Override HuggingFace model cache path")
    parser.add_argument("--python-version", default=None,
        help="Override Python version (default: from profile metadata or .python-version)")
    parser.add_argument("--skip-install", action="store_true",
        help="Skip pip install — only write .env and update config")
    parser.add_argument("--skip-pyenv", action="store_true",
        help="Skip pyenv step (useful if pyenv is not installed)")
    parser.add_argument("--skip-snapshot", action="store_true",
        help="Skip saving pre-change snapshot in performance/current-<machine>-<date>.txt")
    parser.add_argument("--capture-only", "--capture_only", "--capture", action="store_true",
        help="Capture current environment snapshot and planned changes only; do not modify files or install packages")
    parser.add_argument("--reexeced", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    banner("🚀  SkiCycleRun Environment Setup")
    print(f"  📋 Profile:  {args.profile}")
    print(f"  📁 Project:  {PROJECT_ROOT}")

    # 1 ── Parse profile (if provided) ────────────────────────────────────────
    meta: Dict[str, str] = {}
    packages: List[str] = []
    profile_name = ""

    if args.profile:
        profile_path = PROJECT_ROOT / args.profile
        if not profile_path.exists():
            fail(f"Profile not found: {profile_path}")
            sys.exit(1)

        meta, packages = parse_profile(profile_path)
        profile_name = profile_path.name

        step(f"Profile parsed: {profile_name}")
        ok(f"{len(packages)} package specs, {len(meta)} metadata keys")
        if meta:
            print("  📌 Metadata found in profile:")
            for k, v in sorted(meta.items()):
                print(f"       {k}: {v}")
    elif args.capture_only:
        profile_name = _infer_profile_name_from_config()
        step("Capture-only mode (no profile provided)")
        info(f"Using inferred profile label for snapshot context: {profile_name}")
    else:
        parser.error("the following arguments are required: --profile")

    # 2 ── Resolve paths ───────────────────────────────────────────────────────
    # Priority: CLI arg > profile metadata > existing config default > fallback
    existing_config = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
    existing_paths  = existing_config.get("paths", {})

    def _extract_default(s: str) -> str:
        """Pull the default value out of  ${VAR:default}  syntax."""
        m = re.match(r"^\$\{[A-Za-z_][A-Za-z0-9_]*:(.*)\}$", s.strip())
        return m.group(1) if m else s

    config_lib   = _extract_default(existing_paths.get("lib_root",          ""))
    config_cache = _extract_default(existing_paths.get("huggingface_cache",  ""))

    lib_root = (args.lib_root
                or meta.get("lib_root")
                or config_lib
                or str(PROJECT_ROOT))
    hf_cache = (args.hf_cache
                or meta.get("huggingface_cache")
                or config_cache
                or os.path.expanduser("~/.cache/huggingface"))

    print(f"\n  📁 lib_root:          {lib_root}")
    print(f"  🧠 huggingface_cache: {hf_cache}")

    # 3 ── Save rollback snapshot before mutating setup ───────────────────────
    if not args.skip_snapshot and not args.reexeced:
        write_prechange_snapshot(profile_name)
    elif args.skip_snapshot:
        info("--skip-snapshot: pre-change snapshot disabled")
    else:
        info("Snapshot already captured before interpreter handoff")

    if packages:
        print_change_summary(packages, profile_name)
    elif args.capture_only:
        step("Planned dependency changes (pre-apply)")
        info("No profile provided, so no target package delta can be computed.")
        info("Use --profile performance/<name>.txt with --capture-only to preview deltas.")

    if args.capture_only:
        banner("📸  Capture-only mode complete")
        print("  Snapshot and planned changes were recorded/displayed.")
        print("  No files were modified and no packages were installed.")
        print()
        print("  To apply changes later:")
        print(f"    ./run_SetupEnv.sh --profile performance/{profile_name}")
        print()
        return

    # 4 ── Python version ──────────────────────────────────────────────────────
    python_version = (
        args.python_version
        or meta.get("python_version")
        or (PYTHON_VERSION_FILE.read_text().strip() if PYTHON_VERSION_FILE.exists() else "3.13.12")
    )
    if not args.skip_pyenv:
        set_pyenv_version(python_version)
    else:
        info(f"--skip-pyenv: staying on Python {sys.version.split()[0]}")

    maybe_reexec_with_pyenv_python(skip_pyenv=args.skip_pyenv, reexeced=args.reexeced)

    # 5 ── requirements.txt ────────────────────────────────────────────────────
    build_requirements(packages, profile_name)

    # 6 ── pip install ─────────────────────────────────────────────────────────
    if not args.skip_install:
        install_requirements()
    else:
        info("--skip-install: skipping pip install")

    # 7 ── .env ────────────────────────────────────────────────────────────────
    write_env_file(lib_root, hf_cache, meta, profile_name)

    # 8 ── pipeline_config.json ────────────────────────────────────────────────
    update_pipeline_config(lib_root, hf_cache, meta, profile_name)

    # 9 ── Verify (load .env so the verification sees the correct vars) ────────
    for line in ENV_FILE_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

    verify_environment(meta.get("device", "mps"))

    banner("✅  Setup complete!")
    print()
    print("  Run the pipeline in any new shell:")
    print()
    print("    ./run_Pipeline.sh --stages lora_processing")
    print("    ./run_Pipeline.sh                          # all stages")
    print()
    print("  No shell preamble needed — .env is loaded automatically by pipeline.py.")
    print()


if __name__ == "__main__":
    main()
