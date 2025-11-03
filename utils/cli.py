import json, os, sys

def list_loras(base_path="Kontext-Style"):
    from core.lora_registry import discover_loras
    logInfo("📦 Available LoRAs:")
    for name in discover_loras(base_path):
        logInfo(f"  - {name}")

def load_config(path):
    if not os.path.exists(path):
        logInfo(f"❌ Config file not found: {path}")
        sys.exit(1)
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        logInfo(f"❌ Failed to parse config: {e}")
        sys.exit(1)