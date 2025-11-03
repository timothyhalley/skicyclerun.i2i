import os
import sys
import argparse
import json
import argparse
import logging
import time

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
def logInfo(message, level="info"):
    print(message)
    getattr(logging, level)(message)

def logDebug(message):
    if logging.getLogger().isEnabledFor(logging.DEBUG):
        print(f"[DEBUG] {message}")
    logging.debug(message)

def logError(message):
    print(f"❌ {message}")
    logging.error(message)

def logWarn(message):
    print(f"⚠️ {message}")
    logging.warning(message)

# ────────────────────────────────────────────────────────────────────────
# CLI Argument Parsing
# ────────────────────────────────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(description="Kontext Transform CLI")
    parser.add_argument("--config", type=str, default="config/default_config.json", help="Path to config file")
    parser.add_argument("--dry-run", action="store_true", help="Skip inference, log planned actions")
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug logging")
    parser.add_argument("--log-file", type=str, help="Path to log file")
    parser.add_argument("--lora", type=str, help="Override LoRA adapter name")
    parser.add_argument("--list-loras", action="store_true", help="List available LoRA adapters and exit")
    parser.add_argument("--batch", action="store_true", help="Process all images in input folder")
    parser.add_argument("--input-image", type=str, help="Path to a single image to process")  # ← REQUIRED
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--preview", action="store_true", help="Save preprocessed image before inference")
    parser.add_argument("--progress", action="store_true", help="Show simulated progress during inference")
    return parser.parse_args()

# ────────────────────────────────────────────────────────────────────────
# Save result image with timestamp
# ────────────────────────────────────────────────────────────────────────
def save_result(image_path, result_image, config):
    base_name = os.path.splitext(os.path.basename(image_path))[0]
    timestamp = datetime.now().strftime("%d%H%M%S")
    output_name = f"{base_name}_{config['style_name']}_{timestamp}.{config['output_format']}"
    output_path = os.path.join(config["output_folder"], output_name)
    result_image.save(output_path, format=config["output_format"].upper())
    logInfo(f"📁 Saved: {output_path}")

# ────────────────────────────────────────────────────────────────────────
# Batch image discovery
# ────────────────────────────────────────────────────────────────────────
def get_image_files(folder):
    return sorted([
        f for f in glob(os.path.join(folder, "*"))
        if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
    ])

# ────────────────────────────────────────────────────────────────────────
# Main execution
# ────────────────────────────────────────────────────────────────────────
def main():
    args = parse_args()


    # ─────────────────────────────────────────────────────────────
    # Ensure log directory exists
    # ─────────────────────────────────────────────────────────────
    if args.log_file:
        os.makedirs(os.path.dirname(args.log_file), exist_ok=True)

    # ─────────────────────────────────────────────────────────────
    # Logging setup
    # ─────────────────────────────────────────────────────────────
    logging.basicConfig(
        filename=args.log_file if args.log_file else None,
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    # ─────────────────────────────────────────────────────────────
    # LoRA listing shortcut
    # ─────────────────────────────────────────────────────────────
    if args.list_loras:
        list_loras()
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
    # Verbose config output
    # ─────────────────────────────────────────────────────────────
    if args.verbose:
        import json
        logInfo("📊 Verbose Mode Enabled")
        logInfo("🔍 Loaded Config:")
        logInfo(json.dumps(config, indent=2))

    # ─────────────────────────────────────────────────────────────
    # Device resolution (fixes CUDA crash)
    # ─────────────────────────────────────────────────────────────
    import torch
    device = (
        "cuda" if torch.cuda.is_available()
        else "mps" if torch.backends.mps.is_available()
        else "cpu"
    )
    logInfo(f"🎯 Target device: {device} | Precision: {config['precision']}")
    logInfo(f"🎨 Style: {config['style_name']} | Prompt: {config['prompt']}")

    # ─────────────────────────────────────────────────────────────
    # Load pipeline and apply LoRA
    # ─────────────────────────────────────────────────────────────
    pipeline = load_pipeline("black-forest-labs/FLUX.1-Kontext-dev", device, config["precision"], config)

    if args.lora:
        registry = discover_loras()
        lora_cfg = get_lora_config(args.lora, config)  # dynamic override
    else:
        lora_cfg = config["lora"]  # ✅ use full config directly

    apply_lora(pipeline, lora_cfg, config)

    # ─────────────────────────────────────────────────────────────
    # Resolve image paths
    # ─────────────────────────────────────────────────────────────
    if args.batch:
        image_paths = get_image_files(config["input_folder"])
    elif args.input_image:
        image_paths = [args.input_image]
    else:
        image_paths = [os.path.join(config["input_folder"], config["input_image"])]

    # ─────────────────────────────────────────────────────────────
    # Inference loop
    # ─────────────────────────────────────────────────────────────
    for image_path in image_paths:
        if args.dry_run:
            logInfo(f"🧪 Dry run: would process {image_path} with prompt: {config['prompt']}")
            continue

        if args.verbose:
            logInfo(f"🖼️ Processing image: {image_path}")

        image = load_and_prepare_image(image_path, config["max_dim"], config["preprocess"])

        if args.preview:
            preview_path = os.path.join(config["output_folder"], f"preview_{os.path.basename(image_path)}")
            image.save(preview_path)
            logInfo(f"🖼️ Saved preview image: {preview_path}")

        start_time = time.time()
        spinner = Spinner(f"Running inference on {os.path.basename(image_path)}")
        spinner.start()

        result = run_inference(
            pipeline,
            image,
            config["prompt"],
            config["negative_prompt"],
            config["num_inference_steps"],
            config["guidance_scale"]
        )
        output_image = result.images[0]  # extract the actual PIL image

        spinner.stop()
        duration = time.time() - start_time
        logInfo(f"⏱️ Inference completed in {duration:.2f} seconds")

        try:
            save_result(image_path, output_image, config)  # ✅ pass the PIL image here
        except Exception as e:
            logInfo(f"❌ Failed to save result for {image_path}: {e}")

# ────────────────────────────────────────────────────────────────────────
# Entry point
# ────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    main()