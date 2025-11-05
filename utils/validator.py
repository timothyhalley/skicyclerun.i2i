REQUIRED_FIELDS = [
    "input_folder", "output_folder", "input_image",
    "num_inference_steps", "guidance_scale", "device", "precision"
]

def validate_config(config):
    missing = [key for key in REQUIRED_FIELDS if key not in config]
    if missing:
        raise ValueError(f"❌ Missing required config fields: {', '.join(missing)}")