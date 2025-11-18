import os

REQUIRED_FIELDS = [
    "input_folder", "output_folder",
    "num_inference_steps", "guidance_scale", "device", "precision"
]

def validate_config(config):
    """Validate required fields and ensure directory existence.

    Creates missing directories for input/output and parent of input_image.
    Returns True if validation passes.
    """
    missing = [key for key in REQUIRED_FIELDS if key not in config]
    if missing:
        raise ValueError(f"❌ Missing required config fields: {', '.join(missing)}")

    for key in ["input_folder", "output_folder"]:
        path = config.get(key)
        if path and isinstance(path, str):
            try:
                os.makedirs(path, exist_ok=True)
            except Exception as e:
                raise ValueError(f"❌ Failed to ensure directory for '{key}': {path} ({e})")

    single_image = config.get("input_image")
    if single_image and isinstance(single_image, str):
        parent = os.path.dirname(single_image)
        if parent and not os.path.exists(parent):
            try:
                os.makedirs(parent, exist_ok=True)
            except Exception as e:
                raise ValueError(f"❌ Failed to create parent directory for input_image: {parent} ({e})")

    return True