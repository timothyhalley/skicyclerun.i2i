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
    logInfo("=" * 80)
    logInfo(f"🧩 STARTING LoRA APPLICATION: {lora_config['adapter_name']}")
    logInfo(f"📁 LoRA path: {lora_config['path']}")
    logInfo(f"📦 LoRA weights: {lora_config['weights']}")
    logInfo(f"📂 Using cache dir: {config['cache_dir']}")
    logInfo("=" * 80)

    required_keys = ["path", "weights", "adapter_name"]
    missing = [k for k in required_keys if k not in lora_config]
    if missing:
        logError(f"LoRA config missing keys: {missing}")
        raise ValueError(f"Incomplete LoRA config: missing {missing}")

    # Get strength values from lora_config (from registry) or use defaults
    lora_scale = lora_config.get("lora_scale", 0.8)
    text_encoder_scale = lora_config.get("text_encoder_scale", 0.6)
    
    logInfo(f"⚖️  LoRA strength - UNet: {lora_scale}, Text Encoder: {text_encoder_scale}")

    # 🔍 Determine if path is local file or HuggingFace repo
    lora_path = lora_config["path"]
    is_local_file = os.path.exists(lora_path) and os.path.isfile(lora_path)
    
    if is_local_file:
        # Local file path - use directly
        resolved_path = lora_path
        logInfo(f"📦 Using local LoRA file: {resolved_path}")
    else:
        # HuggingFace repo - download from hub
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

    # ✅ Load weights
    if is_local_file:
        logInfo(f"🎨 Loading LoRA weights from local file...")
        pipeline.load_lora_weights(
            resolved_path,
            adapter_name="lora"
        )
    else:
        logInfo(f"🎨 Loading LoRA weights from HuggingFace Hub...")
        pipeline.load_lora_weights(
            lora_config["path"],
            weight_name=lora_config["weights"],
            adapter_name="lora"
        )
    
    # Activate with configurable weights from registry
    pipeline.set_adapters(["lora"], adapter_weights=[lora_scale])
    
    # Set text encoder scale if the pipeline supports it
    # Note: FLUX uses dual text encoders (CLIP-L + T5-XXL)
    if hasattr(pipeline, 'text_encoder') and hasattr(pipeline.text_encoder, 'set_adapter_scale'):
        pipeline.text_encoder.set_adapter_scale('lora', text_encoder_scale)
        logInfo(f"✅ Text encoder scale set to {text_encoder_scale}")
    
    logInfo(f"✅ LoRA '{lora_config['adapter_name']}' loaded and activated successfully.")