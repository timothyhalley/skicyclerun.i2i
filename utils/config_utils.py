import os
import json
from typing import Any, Dict


def _expand_string(value: str, variables: Dict[str, str]) -> str:
    # 1) Expand environment variables like ${VAR}
    expanded = os.path.expandvars(value)
    # 2) Expand {var} placeholders using provided variables
    try:
        expanded = expanded.format(**variables)
    except Exception:
        # If format fails (e.g., brace in text), return best-effort
        pass
    return expanded


def _expand_obj(obj: Any, variables: Dict[str, str]) -> Any:
    if isinstance(obj, str):
        return _expand_string(obj, variables)
    if isinstance(obj, list):
        return [_expand_obj(i, variables) for i in obj]
    if isinstance(obj, dict):
        return {k: _expand_obj(v, variables) for k, v in obj.items()}
    return obj


def resolve_config_placeholders(config: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve placeholders in config using lib_root and environment variables.

    Priority for lib_root:
    1. ENV SKICYCLERUN_LIB_ROOT
    2. config.paths.lib_root
    3. current working directory
    """
    paths = config.get("paths", {})
    env_lib = os.getenv("SKICYCLERUN_LIB_ROOT")
    env_hf_cache = os.getenv("HUGGINGFACE_CACHE_LIB")
    legacy_models_env = os.getenv("SKICYCLERUN_MODEL_LIB")
    env_huggingface_cache = os.getenv("HUGGINGFACE_CACHE")
    env_transformers_cache = os.getenv("TRANSFORMERS_CACHE")
    env_hf_home = os.getenv("HF_HOME")

    configured_root = paths.get("lib_root")
    resolved_config_root = ""
    if configured_root:
        expanded_value = os.path.expandvars(configured_root)
        if expanded_value and expanded_value != configured_root:
            resolved_config_root = expanded_value
        elif "${" in configured_root:
            resolved_config_root = ""
        else:
            resolved_config_root = configured_root

    lib_root = env_lib or resolved_config_root or os.getcwd()

    paths = config.setdefault("paths", {})
    paths["lib_root"] = lib_root

    configured_cache = paths.get("huggingface_cache")
    expanded_cache = os.path.expandvars(configured_cache) if configured_cache else ""

    candidate_paths = [
        env_hf_cache,
        legacy_models_env,
        env_huggingface_cache,
        env_transformers_cache,
        env_hf_home,
        expanded_cache,
    ]

    huggingface_cache = ""
    for candidate in candidate_paths:
        if not candidate:
            continue
        expanded = os.path.expandvars(candidate)
        if expanded:
            huggingface_cache = expanded
            break

    if not huggingface_cache:
        huggingface_cache = os.path.join(lib_root, "models") if lib_root else ""

    paths["huggingface_cache"] = huggingface_cache

    images_root = lib_root
    metadata_root = os.path.join(images_root, "metadata") if images_root else ""
    paths["images_root"] = images_root
    if metadata_root:
        paths["metadata_root"] = metadata_root

    variables = {
        "lib_root": lib_root,
        "images_root": images_root,
        "huggingface_cache": huggingface_cache,
        "metadata_root": metadata_root,
        "models_root": huggingface_cache,  # legacy placeholder support
    }

    return _expand_obj(config, variables)


def expand_with_paths(value: Any, paths: Dict[str, str] | None = None) -> Any:
    """Expand placeholders in arbitrary data using optional path context."""
    wrapper: Dict[str, Any] = {"value": value}
    if paths is not None:
        wrapper["paths"] = dict(paths)
    resolved = resolve_config_placeholders(wrapper)
    return resolved.get("value", value)
