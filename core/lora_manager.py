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

    # 🔍 Determine if path is local file/directory or HuggingFace repo
    lora_path = lora_config["path"]
    weights_filename = lora_config["weights"]
    
    # Debug logging
    logInfo(f"🔍 Checking LoRA path: {lora_path}")
    logInfo(f"🔍 Looking for weights file: {weights_filename}")
    
    # Check if it's a local path (file or directory)
    is_local = os.path.exists(lora_path)
    logInfo(f"🔍 Path exists check: {is_local}")
    
    if is_local:
        # Local path - could be direct file or directory containing weights
        if os.path.isfile(lora_path):
            # Direct path to .safetensors file
            resolved_path = lora_path
            logInfo(f"📦 Using local LoRA file: {resolved_path}")
        elif os.path.isdir(lora_path):
            # Directory containing weights - construct full path
            resolved_path = os.path.join(lora_path, weights_filename)
            logInfo(f"🔍 Constructed full path: {resolved_path}")
            if not os.path.exists(resolved_path):
                logError(f"❌ LoRA weights file not found: {resolved_path}")
                raise FileNotFoundError(f"Weights file not found: {resolved_path}")
            logInfo(f"📦 Using local LoRA from directory: {resolved_path}")
        else:
            logError(f"❌ Invalid local path (not a file or directory): {lora_path}")
            raise ValueError(f"Invalid local path: {lora_path}")
    else:
        # HuggingFace repo - download from hub
        logInfo(f"📥 Downloading LoRA from HuggingFace Hub: {lora_path}")
        try:
            resolved_path = hf_hub_download(
                repo_id=lora_path,
                filename=weights_filename,
                cache_dir=config["cache_dir"]
            )
            logInfo(f"📦 LoRA weights resolved to: {resolved_path}")
        except Exception as e:
            logError(f"Failed to resolve LoRA weights: {e}")
            raise

    # ✅ Load weights - use direct file path for local, or HF repo for remote
    logInfo(f"🎨 Loading LoRA weights...")
    if is_local:
        # Local file - load directly with file path
        pipeline.load_lora_weights(
            resolved_path,
            adapter_name="lora"
        )
    else:
        # HuggingFace Hub - load with repo_id and weight_name
        pipeline.load_lora_weights(
            lora_path,
            weight_name=weights_filename,
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