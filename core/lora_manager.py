import os
from huggingface_hub import hf_hub_download
from utils.logger import logInfo, logError

def discover_loras(base_path="Kontext-Style"):
    return sorted([
        name for name in os.listdir(base_path)
        if os.path.isdir(os.path.join(base_path, name))
    ])

def get_lora_config(name, config, base_path="Kontext-Style"):
    return {
        "path": os.path.join(base_path, name),
        "weights": f"{name}_weights.safetensors",
        "adapter_name": name,
        "cache_dir": config["cache_dir"]
    }

def apply_lora(pipeline, lora_config, config):
    logInfo(f"🧩 Applying LoRA adapter: {lora_config['adapter_name']}")
    logInfo(f"📁 LoRA path: {lora_config['path']}")
    logInfo(f"📦 LoRA weights: {lora_config['weights']}")
    logInfo(f"📂 Using cache dir: {config['cache_dir']}")

    required_keys = ["path", "weights", "adapter_name"]
    missing = [k for k in required_keys if k not in lora_config]
    if missing:
        logError(f"LoRA config missing keys: {missing}")
        raise ValueError(f"Incomplete LoRA config: missing {missing}")

    # 🔍 Resolve and log actual cache path
    try:
        resolved_path = hf_hub_download(
            repo_id=lora_config["path"],
            filename=lora_config["weights"],
            cache_dir=config["cache_dir"]
        )
        logInfo(f"📦 LoRA weights resolved to: {resolved_path}")
    except Exception as e:
        logError(f"Failed to resolve LoRA weights: {e}")
        raise

    # ✅ Load weights - match the working example pattern exactly
    logInfo(f"🎨 Loading LoRA weights from HuggingFace Hub...")
    pipeline.load_lora_weights(
        lora_config["path"],
        weight_name=lora_config["weights"],
        adapter_name="lora"  # Use simple name like working example
    )
    
    # Activate with weight 1.0 (like working example)
    pipeline.set_adapters(["lora"], adapter_weights=[1.0])
    logInfo(f"✅ LoRA '{lora_config['adapter_name']}' loaded and activated successfully.")