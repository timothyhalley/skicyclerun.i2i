from tqdm import tqdm
import threading
import time
from utils.logger import logInfo

def run_inference(pipeline, image, prompt, negative_prompt, steps, guidance):
    logInfo("🧠 Starting inference...")
    
    # Use the actual image dimensions (already properly sized)
    width, height = image.size
    logInfo(f"🖼️  Generating {width}×{height} image (aspect ratio preserved)")

    # Run inference - FLUX provides its own progress bar
    result = pipeline(
        image=image,  # Use explicit image= parameter like working example
        prompt=prompt,
        height=height,
        width=width,
        num_inference_steps=steps
    )

    logInfo("✅ Inference complete.")
    return result