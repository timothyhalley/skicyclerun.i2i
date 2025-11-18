#!/usr/bin/env python3

import gc
import psutil
import torch
from diffusers import FluxKontextPipeline

def get_memory_usage():
    """Get current memory usage in GB"""
    process = psutil.Process()
    return process.memory_info().rss / (1024**3)

def cleanup_memory():
    """Aggressive memory cleanup"""
    gc.collect()
    if torch.backends.mps.is_available():
        torch.mps.empty_cache()

def main():
    print(f"Initial memory: {get_memory_usage():.3f} GB")
    
    # Load pipeline (remove dtype - FLUX doesn't accept it in from_pretrained)
    print("Loading pipeline...")
    pipeline = FluxKontextPipeline.from_pretrained(
        "black-forest-labs/FLUX.1-Kontext-dev",
        device_map="mps"
    )
    
    # Convert to float16 after loading
    pipeline = pipeline.to(dtype=torch.float16)
    
    print(f"Memory after loading: {get_memory_usage():.3f} GB")
    
    # Simple minimal inference test with explicit sizing
    print("Starting minimal inference...")
    try:
        # Try with maximum possible control over dimensions
        image = pipeline(
            prompt="a red apple",
            max_sequence_length=64,  # Minimal sequence length
            num_inference_steps=1,   # Just 1 step to test
            guidance_scale=1.0,      # Minimal guidance
            height=512,              # Try 512 (multiple of 16)
            width=512,               # Try 512 (multiple of 16)
            max_image_sequence_length=64  # Limit image tokens if supported
        ).images[0]
        
        print(f"Memory after inference: {get_memory_usage():.3f} GB")
        print("✅ Inference completed successfully!")
        
    except Exception as e:
        print(f"❌ Inference failed: {e}")
        print(f"Memory when failed: {get_memory_usage():.3f} GB")
    
    finally:
        # Cleanup
        cleanup_memory()
        print(f"Memory after cleanup: {get_memory_usage():.3f} GB")

if __name__ == "__main__":
    main()