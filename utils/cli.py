import json
import os
import sys
from typing import Any, Dict

from utils.config_utils import resolve_config_placeholders
from utils.logger import logInfo


def _expand_defaults(lora_cfg: Dict[str, Any], paths: Dict[str, Any]) -> Dict[str, Any]:
    lib_root = paths.get("lib_root", "")
    default_cache_dir = (
        lora_cfg.get("cache_dir")
        or os.getenv("HUGGINGFACE_CACHE_LIB")
        or os.getenv("HUGGINGFACE_CACHE")
        or os.getenv("HF_HOME")
        or os.path.join(os.path.expanduser("~"), ".cache", "huggingface")
    )
    if isinstance(default_cache_dir, str):
        default_cache_dir = os.path.expandvars(default_cache_dir)

    config: Dict[str, Any] = {
        "paths": paths,
        "input_folder": lora_cfg.get("input_folder") or paths.get("preprocessed") or (os.path.join(lib_root, "pipeline", "scaled") if lib_root else None),
        "output_folder": lora_cfg.get("output_folder") or paths.get("lora_processed") or (os.path.join(lib_root, "pipeline", "lora_processed") if lib_root else None),
        "input_image": lora_cfg.get("input_image"),
        "output_format": lora_cfg.get("output_format", "webp"),
        "max_dim": lora_cfg.get("max_dim", 1024),
        "num_inference_steps": lora_cfg.get("num_inference_steps", 24),
        "guidance_scale": lora_cfg.get("guidance_scale", 3.5),
        "device": lora_cfg.get("device", "mps"),
        "precision": lora_cfg.get("precision", "bfloat16"),
        "preprocess": lora_cfg.get("preprocess", {"enabled": True, "cleanup": True, "face_detection": False}),
        "cache_dir": default_cache_dir,
        "prompt": lora_cfg.get("prompt", ""),
        "negative_prompt": lora_cfg.get("negative_prompt", ""),
        "style_name": lora_cfg.get("style_name"),
    }

    lora_defaults = lora_cfg.get("lora_defaults")
    if lora_defaults:
        config["lora"] = lora_defaults

    return config


def _normalize_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    if "input_folder" in raw and "output_folder" in raw:
        return raw

    lora_cfg = raw.get("lora_processing")
    if not isinstance(lora_cfg, dict):
        return raw

    paths = raw.get("paths", {})
    normalized = _expand_defaults(lora_cfg, paths)
    normalized.setdefault("paths", paths)
    return normalized

def list_loras(base_path="Kontext-Style"):
    from core.lora_registry import discover_loras
    logInfo("📦 Available LoRAs:")
    for name in discover_loras(base_path):
        logInfo(f"  - {name}")

def load_config(path):
    try:
        if not os.path.exists(path):
            logInfo(f"❌ Config file not found: {path}")
            sys.exit(1)

        with open(path, "r") as f:
            raw = json.load(f)
            resolved = resolve_config_placeholders(raw)
            return _normalize_config(resolved)
    except Exception as e:
        logInfo(f"❌ Failed to parse config: {e}")
        sys.exit(1)