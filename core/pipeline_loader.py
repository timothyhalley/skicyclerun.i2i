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
    
    # FLUX works best with bfloat16 (as shown in working example)
    # Use torch_dtype during load for efficiency
    if precision == "float16":
        torch_dtype = torch.bfloat16  # FLUX requires bfloat16, not float16!
    elif precision == "bfloat16":
        torch_dtype = torch.bfloat16
    else:
        torch_dtype = torch.float32
    
    logInfo(f"🚚 Loading pipeline with {torch_dtype}...")
    pipeline = FluxKontextPipeline.from_pretrained(
        model_name,
        torch_dtype=torch_dtype,
        cache_dir=cache_dir
    )
    
    logInfo(f"✅ Pipeline loaded, moving to {device}...")
    pipeline = pipeline.to(device)
    
    return pipeline