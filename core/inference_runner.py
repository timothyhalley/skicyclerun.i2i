from tqdm import tqdm
import threading
import time
import logging

def run_inference(pipeline, image, prompt, negative_prompt, steps, guidance):
    logging.info("🧠 Starting inference...")

    # Start simulated progress bar in a separate thread
    progress_done = False

    def simulate_progress():
        with tqdm(total=100, desc="Inference Progress", unit="%") as pbar:
            while not progress_done:
                time.sleep(0.5)
                pbar.update(2)
                if pbar.n >= 100:
                    pbar.n = 99  # hold at 99% until done
                    pbar.refresh()

    thread = threading.Thread(target=simulate_progress)
    thread.start()

    # Run actual inference
    result = pipeline(
        image,
        prompt=prompt,
        negative_prompt=negative_prompt,
        num_inference_steps=steps,
        guidance_scale=guidance
    )

    # Stop progress bar
    progress_done = True
    thread.join()

    logging.info("✅ Inference complete.")
    return result