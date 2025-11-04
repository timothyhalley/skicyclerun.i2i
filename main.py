import os
import sys
import argparse
import json
import logging
import time
import gc

from datetime import datetime
from utils.cli import load_config, list_loras
from utils.spinner import Spinner
from utils.validator import validate_config
from core.pipeline_loader import load_pipeline
from core.lora_manager import apply_lora
from core.image_processor import load_and_prepare_image
from core.inference_runner import run_inference
from core.lora_registry import discover_loras, get_lora_config
from glob import glob

# ─────────────────────────────────────────────────────────────
# Dual output helper: logInfo to console and log to file
# ─────────────────────────────────────────────────────────────
def logInfo(message, level="info", console_only=False):
    print(message)
    if not console_only:
        getattr(logging, level)(message)

def logDebug(message, console_only=False):
    if logging.getLogger().isEnabledFor(logging.DEBUG):
        print(f"[DEBUG] {message}")
    if not console_only:
        logging.debug(message)

def logError(message):
    print(f"❌ {message}")
    logging.error(message)

def logWarn(message):
    print(f"⚠️ {message}")
    logging.warning(message)

# ─────────────────────────────────────────────────────────────
# Memory management helper
# ─────────────────────────────────────────────────────────────
def cleanup_memory():
    """Force cleanup of PyTorch cache and Python garbage collection"""
    try:
        import torch
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
            # Force synchronization to ensure cleanup completes
            torch.mps.synchronize()
        elif torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
        gc.collect()
        if hasattr(torch, '_C') and hasattr(torch._C, '_cuda_clearCublasWorkspaces'):
            torch._C._cuda_clearCublasWorkspaces()
    except Exception as e:
        logDebug(f"Memory cleanup warning: {e}")

def report_memory_usage():
    """Report current memory usage if debug mode is enabled"""
    try:
        import psutil
        import torch
        
        process = psutil.Process()
        memory_info = process.memory_info()
        memory_mb = memory_info.rss / 1024 / 1024
        
        gpu_memory = "N/A"
        if torch.backends.mps.is_available():
            # MPS doesn't have direct memory reporting, but we can estimate
            gpu_memory = "MPS (memory not directly queryable)"
        elif torch.cuda.is_available():
            gpu_memory = f"{torch.cuda.memory_allocated() / 1024**2:.1f}MB allocated, {torch.cuda.memory_reserved() / 1024**2:.1f}MB reserved"
            
        logDebug(f"Memory usage - RAM: {memory_mb:.1f}MB, GPU: {gpu_memory}")
    except ImportError:
        logDebug("psutil not available for memory reporting")
    except Exception as e:
        logDebug(f"Memory reporting error: {e}")

# ────────────────────────────────────────────────────────────────────────
# CLI Argument Parsing
# ────────────────────────────────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(
        description="FLUX Kontext Image-to-Image Transform CLI - Apply LoRA style transfers to images",
        epilog="""
Examples:
  python main.py                              # Process default image from config
  python main.py --file photo.jpg             # Process specific image
  python main.py --batch                      # Process all images in input folder
  python main.py --lora Anime --file pic.jpg  # Use different LoRA style
  python main.py --dry-run                    # Preview what would be processed
  python main.py --list-loras                 # Show available LoRA styles
  python main.py --help                       # Show this help message

Default config: config/default_config.json (override with --config)
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", type=str, default="config/default_config.json", help="Path to config file")
    parser.add_argument("--dry-run", action="store_true", help="Skip inference, show planned actions (default when no action specified)")
    parser.add_argument("--output-folder", type=str, help="Override output folder path")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging")
    parser.add_argument("--log-file", type=str, help="Path to log file (default: auto-generated in ./logs/log_YYYYMMDD_HHMMSS.log)")
    parser.add_argument("--lora", type=str, help="Override LoRA adapter name")
    parser.add_argument("--list-loras", action="store_true", help="List available LoRA adapters and exit")
    parser.add_argument("--batch", action="store_true", help="Process all images in input folder and subfolders")
    parser.add_argument("--file", type=str, nargs='?', const='', help="Process a specific image file (FQDN path or relative to input folder). If no path specified, uses input_image from config.")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--preview", action="store_true", help="Save preprocessed image before inference")
    parser.add_argument("--progress", action="store_true", help="Show simulated progress during inference")
    parser.add_argument("--low-memory", action="store_true", help="Enable low memory mode (reduces precision and dimensions)")
    parser.add_argument("--cpu-fallback", action="store_true", help="Force CPU usage instead of MPS/CUDA (slower but no memory limits)")
    parser.add_argument("--tiny-mode", action="store_true", help="Ultra-tiny mode: 256px, 8 steps, float16")
    return parser.parse_args()

# ────────────────────────────────────────────────────────────────────────
# Save result image with timestamp (maintains subfolder structure)
# ────────────────────────────────────────────────────────────────────────
def save_result(image_path, result_image, config, input_base_folder=None, lora_name=None):
    base_name = os.path.splitext(os.path.basename(image_path))[0]
    timestamp = datetime.now().strftime("%d%H%M%S")
    # Use lora_name if provided, otherwise fall back to config style_name
    style = lora_name if lora_name else config['style_name']
    output_name = f"{base_name}_{style}_{timestamp}.{config['output_format']}"
    
    # Maintain subfolder structure if processing batch from input folder
    if input_base_folder and image_path.startswith(input_base_folder):
        # Get relative path from input folder
        rel_path = os.path.relpath(os.path.dirname(image_path), input_base_folder)
        if rel_path != ".":  # If in a subfolder
            output_subfolder = os.path.join(config["output_folder"], rel_path)
            os.makedirs(output_subfolder, exist_ok=True)
            output_path = os.path.join(output_subfolder, output_name)
        else:
            output_path = os.path.join(config["output_folder"], output_name)
    else:
        output_path = os.path.join(config["output_folder"], output_name)
    
    result_image.save(output_path, format=config["output_format"].upper())
    logInfo(f"📁 Saved: {output_path}")

# ────────────────────────────────────────────────────────────────────────
# Batch image discovery (recursive)
# ────────────────────────────────────────────────────────────────────────
def get_image_files(folder):
    image_files = []
    # Use recursive glob to find images in all subfolders
    for pattern in ["*.png", "*.jpg", "*.jpeg", "*.webp", "*.PNG", "*.JPG", "*.JPEG", "*.WEBP"]:
        image_files.extend(glob(os.path.join(folder, "**", pattern), recursive=True))
    return sorted(image_files)

# ────────────────────────────────────────────────────────────────────────
# Main execution
# ────────────────────────────────────────────────────────────────────────
def main():
    args = parse_args()


    # Note: logging setup is deferred until after we load the config so
    # defaults from the config file can affect what we display to the user.

    # ─────────────────────────────────────────────────────────────
    # LoRA listing shortcut
    # ─────────────────────────────────────────────────────────────
    if args.list_loras:
        import json as json_module  # Explicit import to avoid any shadowing issues
        try:
            with open("config/lora_registry.json", "r") as f:
                lora_registry = json_module.load(f)
            logInfo("🎨 Available LoRA Styles:")
            logInfo("=" * 80)
            for name, info in sorted(lora_registry.items()):
                logInfo(f"  • {name:<20} - {info['description']}")
            logInfo("=" * 80)
            logInfo(f"\nTotal: {len(lora_registry)} styles available")
            logInfo("\nUsage: python main.py --lora <style_name> --file <image>")
            logInfo("Example: python main.py --lora 3D_Chibi --file photo.jpg")
        except Exception as e:
            logError(f"Failed to load LoRA registry: {e}")
        sys.exit(0)

    # ─────────────────────────────────────────────────────────────
    # Load and validate config
    # ─────────────────────────────────────────────────────────────
    try:
        config = load_config(args.config)
        validate_config(config)
    except Exception as e:
        logInfo(f"❌ Failed to load or validate config: {e}")
        sys.exit(1)

    # ─────────────────────────────────────────────────────────────
    # Finalize logging using CLI override or auto-generate timestamped log
    # ─────────────────────────────────────────────────────────────
    effective_log_file = args.log_file
    
    # If no log file specified, create timestamped log in ./logs/
    if not effective_log_file:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)
        effective_log_file = os.path.join(log_dir, f"log_{timestamp}.log")
        logInfo(f"📝 Auto-generating log file: {effective_log_file}")
    
    # Ensure log directory exists
    if effective_log_file:
        os.makedirs(os.path.dirname(effective_log_file), exist_ok=True)

    logging.basicConfig(
        filename=effective_log_file if effective_log_file else None,
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )
    
    # ─────────────────────────────────────────────────────────────
    # Device selection with CPU fallback option (before computing effective settings)
    # ─────────────────────────────────────────────────────────────
    import torch
    
    if args.cpu_fallback:
        device = "cpu"
        logInfo("💻 CPU fallback mode enabled - slower but no memory limits")
    else:
        device = (
            "cuda" if torch.cuda.is_available()
            else "mps" if torch.backends.mps.is_available()
            else "cpu"
        )

    # ─────────────────────────────────────────────────────────────
    # Compute and echo effective defaults (what will be used)
    # ─────────────────────────────────────────────────────────────
    # Resolve input path(s)
    if args.batch:
        resolved_input = config.get("input_folder")
        input_type = "batch_folder"
    elif args.file is not None:  # --file was specified (even if empty)
        if args.file:  # Non-empty path provided
            # If --file is FQDN path (absolute), use as-is; otherwise assume relative to input_folder
            if os.path.isabs(args.file):
                resolved_input = args.file
            else:
                resolved_input = os.path.join(config.get("input_folder", ""), args.file)
            input_type = "single_file_cli"
        else:  # --file specified but no path, use config
            resolved_input = config.get("input_image")
            input_type = "single_file_config"
    else:
        resolved_input = os.path.join(config.get("input_folder", ""), config.get("input_image", ""))
        input_type = "default_image"

    # Override config with CLI args if provided
    if args.output_folder:
        config["output_folder"] = args.output_folder
    
    # Low memory mode overrides
    if args.low_memory:
        config["precision"] = "float16"
        config["max_dim"] = min(config.get("max_dim", 1024), 512)
        config["num_inference_steps"] = min(config.get("num_inference_steps", 24), 12)
        logInfo("🧠 Low memory mode enabled: float16, max_dim=512, steps=12")
    
    # Ultra-tiny mode for extreme memory constraints
    if args.tiny_mode:
        config["precision"] = "float16"
        config["max_dim"] = 256
        config["num_inference_steps"] = 8
        logInfo("🐭 Tiny mode enabled: float16, max_dim=256, steps=8")
    
    effective = {
        "config_file": args.config,
        "input": resolved_input,
        "input_type": input_type,
        "output_folder": config.get("output_folder"),
        "log_file": effective_log_file if effective_log_file else "STDOUT",
        "log_level": "DEBUG" if args.debug else "INFO",
        "style_name": config.get("style_name"),
        "lora": args.lora if args.lora else (config.get("lora") and config.get("lora").get("adapter_name")) or config.get("lora"),
        "device": device,  # Use the computed device instead of config device
        "precision": config.get("precision"),
        "prompt": config.get("prompt"),
        "negative_prompt": config.get("negative_prompt"),
        "output_format": config.get("output_format")
    }

    # Display configuration with proper formatting and emojis
    logInfo("\n🔧 Configuration settings:", console_only=True)
    
    config_emojis = {
        "config_file": "🧾",         # Scroll for config nuance; more distinct than 📄
        "input": "🖼️",              # Image remains appropriate
        "input_type": "🧭",          # Compass suggests direction or type
        "output_folder": "🗃️",       # Archive box implies structured output
        "log_file": "📜",            # Scroll evokes logs/history
        "log_level": "📶",           # Signal bars suggest verbosity/intensity
        "style_name": "🧵",          # Thread for style/design metaphor
        "lora": "🧠",                # Brain for learned adapters and intelligence
        "device": "🖥️",              # Desktop for hardware context
        "precision": "🎯",           # Bullseye for accuracy
        "prompt": "🗣️",              # Speech for user intent
        "negative_prompt": "🙈",     # See-no-evil for suppression or avoidance
        "output_format": "📦"        # Package for format/container metaphor
    }
    
    for key, value in effective.items():
        emoji = config_emojis.get(key, "🔧")
        logInfo(f"        {emoji}  {key}: {value}", console_only=True)

    # ─────────────────────────────────────────────────────────────
    # Verbose config output
    # ─────────────────────────────────────────────────────────────
    if args.verbose:
        import json
        logInfo("📊 Verbose Mode Enabled")
        logInfo("🔍 Loaded Config:")
        logInfo(json.dumps(config, indent=2))

    # ─────────────────────────────────────────────────────────────
    # Check if no meaningful args provided - default to dry-run
    # ─────────────────────────────────────────────────────────────
    no_action_args = not any([
        args.batch, args.file is not None, args.list_loras,
        not args.dry_run and len(sys.argv) > 1  # Has args but not just dry-run
    ])
    
    if args.dry_run or no_action_args:
        logInfo("\n🧪 DRY RUN MODE - No processing will occur\n", console_only=True)
        
        # Show what would be processed
        if args.batch:
            image_files = get_image_files(config["input_folder"])
            logInfo(f"        📂 Would process {len(image_files)} images from: {config['input_folder']}", console_only=True)
            if args.verbose:
                for i, img in enumerate(image_files[:5], 1):  # Show first 5
                    logInfo(f"            {i}. {os.path.basename(img)}", console_only=True)
                if len(image_files) > 5:
                    logInfo(f"            ... and {len(image_files) - 5} more", console_only=True)
        else:
            target_image = resolved_input
            logInfo(f"        🖼️  Would process single image: {target_image}", console_only=True)
            
        logInfo(f"        💾  Would save results to: {config['output_folder']}", console_only=True)
        logInfo(f"        🎨  Using style '{config['style_name']}' with LoRA: {effective['lora']}", console_only=True)
        logInfo(f"        💭  Prompt: {config['prompt']}", console_only=True)
        logInfo(f"        🚫  Negative prompt: {config['negative_prompt']}", console_only=True)
        logInfo(f"        ⚙️  Inference steps: {config['num_inference_steps']} | Guidance: {config['guidance_scale']}", console_only=True)
        
        if no_action_args:  # Show CLI primer only when run without args
            logInfo("\n📖 CLI Parameters Quick Reference:", console_only=True)
            logInfo("        --batch                  Process all images in input folder and subfolders", console_only=True)
            logInfo("        --file PATH              Process a specific image file (FQDN or relative to input folder)", console_only=True)
            logInfo("        --lora NAME              Override LoRA adapter (use --list-loras to see options)", console_only=True)
            logInfo("        --config PATH            Use different config file", console_only=True)
            logInfo("        --output-folder PATH     Override output directory", console_only=True)
            logInfo("        --verbose                Enable detailed logging", console_only=True)
            logInfo("        --debug                  Enable debug mode with stack traces", console_only=True)
            logInfo("        --low-memory             Reduce memory usage (512px, 12 steps, float16)", console_only=True)
            logInfo("        --tiny-mode              Ultra-low memory (256px, 8 steps, float16)", console_only=True)
            logInfo("        --cpu-fallback           Force CPU mode (slower, unlimited memory)", console_only=True)
            logInfo("        --dry-run                Show what would be processed (default when no action specified)", console_only=True)
            logInfo("        --list-loras             List available LoRA adapters", console_only=True)
            logInfo("\n        Example: python main.py --file my_photo.jpg --lora Anime", console_only=True)
        
        logInfo("\n✅ Dry run complete - no memory or GPU resources used", console_only=True)
        sys.exit(0)

    if args.debug:
        logDebug(f"PyTorch version: {torch.__version__}")
        logDebug(f"CUDA available: {torch.cuda.is_available()}")
        logDebug(f"MPS available: {torch.backends.mps.is_available() if hasattr(torch.backends, 'mps') else False}")
        
    # Force aggressive memory cleanup before starting
    cleanup_memory()
        
    logInfo(f"🎯 Target device: {device} | Precision: {config['precision']}")
    logInfo(f"🎨 Style: {config['style_name']} | Prompt: {config['prompt']}")

    # Warn if using float32 on MPS (memory intensive)
    if device == "mps" and config.get('precision') == 'float32':
        logWarn("Using float32 on MPS can cause memory issues. Consider using float16 in config.")
        
    # Set MPS memory fraction if available
    if device == "mps":
        # More aggressive memory management for MPS
        os.environ['PYTORCH_MPS_HIGH_WATERMARK_RATIO'] = '0.0'  # Disable upper limit as suggested
        os.environ['PYTORCH_MPS_LOW_WATERMARK_RATIO'] = '0.7'   # Keep 70% for other processes
        logInfo("🧠 MPS memory management: disabled upper limit, 70% low watermark")

    # ─────────────────────────────────────────────────────────────
    # Load pipeline and apply LoRA
    # ─────────────────────────────────────────────────────────────
    if args.debug:
        logDebug("Loading pipeline: black-forest-labs/FLUX.1-Kontext-dev")
        
    pipeline = load_pipeline("black-forest-labs/FLUX.1-Kontext-dev", device, config["precision"], config)

    if args.lora:
        # Load LoRA from registry
        import json as json_module  # Explicit import to avoid shadowing
        try:
            with open("config/lora_registry.json", "r") as f:
                lora_registry = json_module.load(f)
            
            # Case-insensitive lookup - find the correct case
            lora_key = None
            for key in lora_registry.keys():
                if key.lower() == args.lora.lower():
                    lora_key = key
                    break
            
            if not lora_key:
                logError(f"❌ LoRA '{args.lora}' not found in registry. Use --list-loras to see available styles.")
                sys.exit(1)
            
            lora_info = lora_registry[lora_key]
            lora_cfg = {
                "adapter_name": lora_key,
                "path": lora_info["path"],
                "weights": lora_info["weights"]
            }
            
            # Override prompts with LoRA-specific prompts if available
            if "prompt" in lora_info:
                config["prompt"] = lora_info["prompt"]
                logInfo(f"📝 Using LoRA-specific prompt")
            if "negative_prompt" in lora_info:
                config["negative_prompt"] = lora_info["negative_prompt"]
            
            logInfo(f"🎨 Using LoRA style: {lora_key} - {lora_info['description']}")
            
            if args.debug:
                logDebug(f"LoRA override config: {lora_cfg}")
                logDebug(f"Prompt: {config['prompt']}")
                logDebug(f"Negative prompt: {config['negative_prompt']}")
        except Exception as e:
            logError(f"Failed to load LoRA registry: {e}")
            sys.exit(1)
    else:
        lora_cfg = config["lora"]  # ✅ use full config directly
        
    if args.debug:
        logDebug(f"Applying LoRA configuration: {lora_cfg}")

    apply_lora(pipeline, lora_cfg, config)
    
    # Initial memory cleanup after model loading
    cleanup_memory()
    if args.debug:
        report_memory_usage()
    
    # Initial memory cleanup after model loading
    cleanup_memory()
    if args.debug:
        report_memory_usage()

    # ─────────────────────────────────────────────────────────────
    # Resolve image paths
    # ─────────────────────────────────────────────────────────────
    input_base_folder = None
    if args.batch:
        input_base_folder = config["input_folder"]
        image_paths = get_image_files(config["input_folder"])
        if args.debug:
            logDebug(f"Found {len(image_paths)} images in {input_base_folder} (including subfolders)")
    elif args.file is not None:
        image_paths = [resolved_input]  # Use the resolved path from earlier logic
    else:
        image_paths = [resolved_input]  # Use the default image path

    # ─────────────────────────────────────────────────────────────
    # Inference loop
    # ─────────────────────────────────────────────────────────────
    
    # Track batch progress
    batch_start_time = time.time()
    total_files = len(image_paths)
    
    # Print batch header if processing multiple files
    if total_files > 1:
        logInfo("\n" + "=" * 80)
        logInfo(f"📦 BATCH PROCESSING: {total_files} images found")
        logInfo("=" * 80 + "\n")
    
    for i, image_path in enumerate(image_paths, 1):
        file_start_time = time.time()
        
        # Print file header for batch processing
        if total_files > 1:
            logInfo("\n" + "─" * 80)
            logInfo(f"🖼️  Processing [{i}/{total_files}]: {os.path.basename(image_path)}")
            logInfo(f"📍 Path: {image_path}")
            logInfo("─" * 80)
        elif args.verbose:
            logInfo(f"\n🖼️ Processing: {os.path.basename(image_path)}")
            logInfo(f"   📍 Full path: {image_path}")
            
        if args.debug:
            logDebug(f"Loading and preparing image: {image_path}")
            logDebug(f"Max dimension: {config['max_dim']}, Preprocess: {config['preprocess']}")

        image = load_and_prepare_image(image_path, config["max_dim"], config["preprocess"])
        
        if args.debug:
            logDebug(f"Image loaded - Size: {image.size}, Mode: {image.mode}")

        if args.preview:
            preview_path = os.path.join(config["output_folder"], f"preview_{os.path.basename(image_path)}")
            image.save(preview_path)
            logInfo(f"🖼️ Saved preview image: {preview_path}")

        start_time = time.time()
        
        if args.verbose:
            logInfo(f"🚀 Starting inference with {config['num_inference_steps']} steps...")
            
        spinner = Spinner(f"Running inference on {os.path.basename(image_path)}")
        if not args.verbose:  # Don't show spinner if verbose (conflicts with output)
            spinner.start()

        if args.debug:
            logDebug(f"Calling run_inference with prompt: '{config['prompt']}'")
            logDebug(f"Negative prompt: '{config['negative_prompt']}'")
            logDebug(f"Steps: {config['num_inference_steps']}, Guidance: {config['guidance_scale']}")

        result = run_inference(
            pipeline,
            image,
            config["prompt"],
            config["negative_prompt"],
            config["num_inference_steps"],
            config["guidance_scale"]
        )
        output_image = result.images[0]  # extract the actual PIL image

        if not args.verbose:
            spinner.stop()
            
        file_duration = time.time() - file_start_time
        
        # Format duration nicely
        file_mins = int(file_duration // 60)
        file_secs = int(file_duration % 60)
        file_time_str = f"{file_mins}m {file_secs}s" if file_mins > 0 else f"{file_secs}s"
        
        # Calculate accumulated time
        accumulated_time = time.time() - batch_start_time
        acc_hours = int(accumulated_time // 3600)
        acc_mins = int((accumulated_time % 3600) // 60)
        acc_secs = int(accumulated_time % 60)
        acc_time_str = f"{acc_hours:02d}:{acc_mins:02d}:{acc_secs:02d}"
        
        # Log completion for this file
        if total_files > 1:
            logInfo(f"\n✅ Completed in {file_time_str} | Accumulated time: {acc_time_str}")
        else:
            logInfo(f"⏱️  Inference completed in {file_time_str}")
        
        if args.debug:
            logDebug(f"Result image - Size: {output_image.size}, Mode: {output_image.mode}")

        try:
            save_result(image_path, output_image, config, input_base_folder, lora_name=lora_cfg["adapter_name"])  # ✅ pass the PIL image and LoRA name here
            if args.verbose:
                logInfo(f"✅ Successfully saved result for {os.path.basename(image_path)}")
        except Exception as e:
            logError(f"Failed to save result for {image_path}: {e}")
            if args.debug:
                import traceback
                logDebug(f"Save error traceback: {traceback.format_exc()}")
        
        # Clean up memory after each image to prevent accumulation
        cleanup_memory()
        if args.debug and len(image_paths) > 1:
            report_memory_usage()
    
    # Print batch summary if multiple files
    if total_files > 1:
        total_time = time.time() - batch_start_time
        total_hours = int(total_time // 3600)
        total_mins = int((total_time % 3600) // 60)
        total_secs = int(total_time % 60)
        total_time_str = f"{total_hours:02d}:{total_mins:02d}:{total_secs:02d}"
        avg_time = total_time / total_files
        avg_mins = int(avg_time // 60)
        avg_secs = int(avg_time % 60)
        avg_time_str = f"{avg_mins}m {avg_secs}s" if avg_mins > 0 else f"{avg_secs}s"
        
        logInfo("\n" + "=" * 80)
        logInfo(f"🎉 BATCH COMPLETE: {total_files} images processed")
        logInfo(f"⏱️  Total time: {total_time_str}")
        logInfo(f"📊 Average time per image: {avg_time_str}")
        logInfo("=" * 80 + "\n")
    
    # Final cleanup
    cleanup_memory()
    if args.debug:
        logDebug("Final memory cleanup completed")

# ────────────────────────────────────────────────────────────────────────
# Entry point
# ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()