import os
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


def compile_pipeline_transformer(pipeline, device: str | None = None) -> None:
    """Apply torch.compile to pipeline.transformer (opt-in via env vars).

    Must be called AFTER load_lora_weights() / apply_lora() — PEFT adapter
    injection does not work on a compiled module.
    """
    compile_enabled = os.getenv("SKICYCLERUN_TORCH_COMPILE", "0").strip().lower() in {
        "1", "true", "yes", "on"
    }
    if not compile_enabled:
        return

    compile_backend = os.getenv("SKICYCLERUN_TORCH_COMPILE_BACKEND", "inductor").strip()
    compile_mode = os.getenv("SKICYCLERUN_TORCH_COMPILE_MODE", "max-autotune-no-cudagraphs").strip()
    compile_on_mps = os.getenv("SKICYCLERUN_TORCH_COMPILE_ON_MPS", "0").strip().lower() in {
        "1", "true", "yes", "on"
    }
    allow_mps_inductor = os.getenv("SKICYCLERUN_TORCH_COMPILE_ALLOW_MPS_INDUCTOR", "0").strip().lower() in {
        "1", "true", "yes", "on"
    }
    transformer = getattr(pipeline, "transformer", None)

    if transformer is None:
        logWarn("⚠️ torch.compile requested but pipeline.transformer is missing; skipping compile")
        return
    elif not hasattr(torch, "compile"):
        logWarn("⚠️ torch.compile requested but unavailable in this torch build; skipping compile")
        return

    # MPS + inductor is still prototype-quality in upstream torch and is known
    # to fail on some FLUX reduction kernels. Keep MPS inference enabled but
    # skip compile unless explicitly requested.
    normalized_device = (device or "").strip().lower()
    if not normalized_device:
        transformer_device = getattr(transformer, "device", None)
        normalized_device = str(transformer_device).strip().lower() if transformer_device else ""
    is_mps_device = normalized_device.startswith("mps")

    if is_mps_device and not compile_on_mps:
        logWarn(
            "⚠️ torch.compile auto-disabled on MPS for stability; running uncompiled on MPS. "
            "Set SKICYCLERUN_TORCH_COMPILE_ON_MPS=1 to force-enable."
        )
        return

    if is_mps_device and compile_backend == "inductor" and not allow_mps_inductor:
        logWarn(
            "⚠️ SKICYCLERUN_TORCH_COMPILE_BACKEND=inductor is unstable on MPS; "
            "switching to backend=aot_eager. Set SKICYCLERUN_TORCH_COMPILE_ALLOW_MPS_INDUCTOR=1 to override."
        )
        compile_backend = "aot_eager"
        if compile_mode == "max-autotune-no-cudagraphs":
            compile_mode = "reduce-overhead"

    try:
        compile_kwargs = {
            "backend": compile_backend,
            "fullgraph": False,
        }
        # mode is primarily meaningful for inductor; avoid backend-specific mode errors.
        if compile_backend == "inductor":
            compile_kwargs["mode"] = compile_mode

        mode_desc = compile_kwargs.get("mode", "<default>")
        logInfo(
            f"🧪 Compiling pipeline.transformer (backend={compile_backend}, mode={mode_desc})"
        )
        pipeline.transformer = torch.compile(transformer, **compile_kwargs)
        logInfo("✅ torch.compile applied to pipeline.transformer")
    except Exception as compile_err:
        logWarn(f"⚠️ torch.compile failed, continuing uncompiled: {compile_err}")