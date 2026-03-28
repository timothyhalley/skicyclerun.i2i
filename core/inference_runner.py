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

    # Run inference - FLUX provides its own progress bar, but MPS can spend
    # noticeable time on first-call graph compilation before progress advances.
    logInfo("⏳ Entering diffusion loop (first image may pause while kernels compile)")
    start_t = time.perf_counter()
    heartbeat_stop = threading.Event()

    def _heartbeat():
        while not heartbeat_stop.wait(20):
            elapsed = time.perf_counter() - start_t
            logInfo(f"⏱️  Inference still running... {elapsed:.0f}s elapsed")

    hb_thread = threading.Thread(target=_heartbeat, daemon=True)
    hb_thread.start()

    try:
        with torch.inference_mode():
            result = pipeline(
                image=image,  # Use explicit image= parameter like working example
                prompt=prompt,
                negative_prompt=negative_prompt,
                height=height,
                width=width,
                num_inference_steps=steps,
                guidance_scale=guidance,
                generator=generator
            )
    finally:
        heartbeat_stop.set()
        hb_thread.join(timeout=0.2)

    total_t = time.perf_counter() - start_t
    logInfo(f"✅ Diffusion loop finished in {total_t:.1f}s")

    logInfo("✅ Inference complete.")
    return result