from tqdm import tqdm
import threading
import time
import torch
from utils.logger import logInfo

def run_inference(pipeline, image, prompt, negative_prompt, steps, guidance, seed=None, device="mps"):
    logInfo("🧠 Starting inference...")
    
    # Use the actual image dimensions (already properly sized)
    width, height = image.size
    logInfo(f"🖼️  Generating {width}×{height} image (aspect ratio preserved)")
    
    # Set up generator with seed for reproducibility
    generator = None
    if seed is not None:
        generator = torch.Generator(device=device).manual_seed(seed)
        logInfo(f"🎲 Using seed: {seed}")

    # Run inference - FLUX provides its own progress bar
    result = pipeline(
        image=image,  # Use explicit image= parameter like working example
        prompt=prompt,
        height=height,
        width=width,
        num_inference_steps=steps,
        generator=generator
    )

    logInfo("✅ Inference complete.")
    return result