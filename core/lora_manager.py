import os
import logging
from huggingface_hub import hf_hub_download

logging.basicConfig(level=logging.INFO)

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
    logging.info(f"🧩 Applying LoRA adapter: {lora_config['adapter_name']}")
    logging.info(f"📁 LoRA path: {lora_config['path']}")
    logging.info(f"📦 LoRA weights: {lora_config['weights']}")
    logging.info(f"📂 Using cache dir: {config['cache_dir']}")

    required_keys = ["path", "weights", "adapter_name"]
    missing = [k for k in required_keys if k not in lora_config]
    if missing:
        logging.error(f"❌ LoRA config missing keys: {missing}")
        raise ValueError(f"Incomplete LoRA config: missing {missing}")

    # 🔍 Resolve and log actual cache path
    try:
        resolved_path = hf_hub_download(
            repo_id=lora_config["path"],
            filename=lora_config["weights"],
            cache_dir=config["cache_dir"]
        )
        logging.info(f"📦 LoRA weights resolved to: {resolved_path}")
    except Exception as e:
        logging.error(f"❌ Failed to resolve LoRA weights: {e}")
        raise

    # ✅ Load weights - match the working example pattern exactly
    logging.info(f"🎨 Loading LoRA weights from HuggingFace Hub...")
    pipeline.load_lora_weights(
        lora_config["path"],
        weight_name=lora_config["weights"],
        adapter_name="lora"  # Use simple name like working example
    )
    
    # Activate with weight 1.0 (like working example)
    pipeline.set_adapters(["lora"], adapter_weights=[1.0])
    logging.info(f"✅ LoRA '{lora_config['adapter_name']}' loaded and activated successfully.")