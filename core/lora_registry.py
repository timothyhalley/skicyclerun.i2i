import os
import logging

logging.basicConfig(level=logging.INFO)

def discover_loras(base_path="Kontext-Style"):
    """
    Returns a sorted list of available LoRA adapter names (folder names).
    """
    if not os.path.exists(base_path):
        logging.info(f"⚠️ LoRA base path not found: {base_path}")
        return []

    return sorted([
        name for name in os.listdir(base_path)
        if os.path.isdir(os.path.join(base_path, name))
    ])

def get_lora_config(adapter_name, base_path="Kontext-Style"):
    """
    Constructs a LoRA config dictionary for the given adapter name.
    Assumes weights file is named <adapter_name>_weights.safetensors.
    """
    adapter_path = os.path.join(base_path, adapter_name)
    weights_file = f"{adapter_name}_weights.safetensors"

    if not os.path.exists(adapter_path):
        raise FileNotFoundError(f"❌ LoRA adapter folder not found: {adapter_path}")

    weights_path = os.path.join(adapter_path, weights_file)
    if not os.path.exists(weights_path):
        raise FileNotFoundError(f"❌ LoRA weights file not found: {weights_path}")

    return {
        "path": adapter_path,
        "weights": weights_file,
        "adapter_name": adapter_name
    }