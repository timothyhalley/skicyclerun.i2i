import torch
from diffusers import FluxKontextPipeline
from utils.logger import logInfo, logError, logWarn, logDebug   

def resolve_device(config_device):
    """
    Validates and resolves the device string from config.
    Falls back to CPU if requested device is unavailable.
    """
    if config_device == "cuda" and not torch.cuda.is_available():
        logInfo("⚠️ CUDA not available. Falling back to CPU.")
        return "cpu"
    elif config_device == "mps" and not torch.backends.mps.is_available():
        logInfo("⚠️ MPS not available. Falling back to CPU.")
        return "cpu"
    return config_device

def load_pipeline(model_name, device, precision, config):
    logInfo(f"🔧 Initializing pipeline: {model_name} on {device} with {precision}")
    cache_dir = config["cache_dir"]
    logInfo("📦 Loading model config and tokenizer...")

    variant = config.get("variant")  # optional in config

    logInfo("🚚 Loading pipeline components from cache...")
    pipeline = FluxKontextPipeline.from_pretrained(
        model_name,
        dtype=torch.float32 if precision == "float32" else torch.float16,
        cache_dir=config["cache_dir"],
        revision="main",
        use_safetensors=True,
        **({"variant": variant} if variant else {})  # ✅ only pass if defined
    )
    logInfo("✅ Pipeline components loaded into memory.")

    pipeline.to(device)
    return pipeline