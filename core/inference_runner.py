from tqdm import tqdm
import threading
import time
import logging

def run_inference(pipeline, image, prompt, negative_prompt, steps, guidance):
    logging.info("🧠 Starting inference...")
    
    # Use the actual image dimensions (already properly sized)
    width, height = image.size
    logging.info(f"🖼️  Generating {width}×{height} image (aspect ratio preserved)")

    # Run inference - FLUX provides its own progress bar
    result = pipeline(
        image=image,  # Use explicit image= parameter like working example
        prompt=prompt,
        height=height,
        width=width,
        num_inference_steps=steps
    )

    logging.info("✅ Inference complete.")
    return result