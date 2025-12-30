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
    # Use dtype parameter for pipeline loading
    if precision == "float16":
        dtype = torch.bfloat16  # FLUX requires bfloat16, not float16!
    elif precision == "bfloat16":
        dtype = torch.bfloat16
    else:
        dtype = torch.float32
    
    # Check if local-only mode is enabled in config
    local_files_only = config.get("local_files_only", True)
    
    try:
        logInfo(f"🚚 Loading pipeline with {dtype}...")
        logInfo(f"📁 Cache directory: {cache_dir}")
        if local_files_only:
            logInfo(f"🔒 Using local models only (no network access)")
        
        pipeline = FluxKontextPipeline.from_pretrained(
            model_name,
            cache_dir=cache_dir,
            local_files_only=local_files_only
        )
        
        logInfo(f"✅ Pipeline loaded, moving to {device}...")
        pipeline = pipeline.to(device, dtype=dtype)
        
        return pipeline
        
    except Exception as e:
        # Handle HuggingFace authentication errors gracefully
        error_msg = str(e)
        
        if "GatedRepoError" in str(type(e).__name__) or "401" in error_msg or "Unauthorized" in error_msg:
            logError("=" * 80)
            logError("🔐 AUTHENTICATION REQUIRED")
            logError("=" * 80)
            logError(f"❌ Cannot access model: {model_name}")
            logError("")
            logError("This model requires HuggingFace authentication. You have two options:")
            logError("")
            logError("OPTION 1: Use local models only (recommended)")
            logError("   • Set 'local_files_only': true in your config file")
            logError("   • Ensure models are cached at: {cache_dir}")
            logError("")
            logError("OPTION 2: Authenticate with HuggingFace")
            logError("   1. Get your token from: https://huggingface.co/settings/tokens")
            logError("   2. Run: huggingface-cli login")
            logError("   3. Accept model license: https://huggingface.co/{model_name}")
            logError("")
            logError("=" * 80)
            raise RuntimeError("HuggingFace authentication required. See instructions above.") from e
        
        elif "OSError" in str(type(e).__name__) and local_files_only:
            logError("=" * 80)
            logError("📦 MODEL NOT FOUND IN LOCAL CACHE")
            logError("=" * 80)
            logError(f"❌ Model '{model_name}' not found in cache directory")
            logError(f"📁 Cache location: {cache_dir}")
            logError("")
            logError("Solutions:")
            logError("   1. Download the model first (disable local_files_only temporarily)")
            logError("   2. Verify the cache directory path is correct")
            logError("   3. Check that the model has been previously downloaded")
            logError("")
            logError("=" * 80)
            raise RuntimeError(f"Model not found in local cache: {cache_dir}") from e
        
        # Re-raise other errors
        raise