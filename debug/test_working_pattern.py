#!/usr/bin/env python3
"""
Test script using the EXACT working pattern you provided.
This should produce a colored Ghibli-style image, not black.
"""

from diffusers import FluxKontextPipeline
from diffusers.utils import load_image
import torch
import os, json
from utils.config_utils import resolve_config_placeholders

print("🔧 Loading pipeline with bfloat16 (working pattern)...")
with open("config/pipeline_config.json","r") as f:
    cfg = resolve_config_placeholders(json.load(f))
lib_root = cfg.get("paths",{}).get("lib_root") or os.getcwd()
hf_cache = cfg.get("paths",{}).get("huggingface_cache") or os.path.normpath(os.path.join(lib_root, "..", "models"))

pipeline = FluxKontextPipeline.from_pretrained(
    "black-forest-labs/FLUX.1-Kontext-dev", 
    dtype=torch.bfloat16,
    cache_dir=hf_cache
).to('mps')

print("🎨 Loading LoRA adapter...")
pipeline.load_lora_weights(
    "Kontext-Style/Ghibli_lora", 
    weight_name="Ghibli_lora_weights.safetensors", 
    adapter_name="lora"
)
pipeline.set_adapters(["lora"], adapter_weights=[1])

print("🖼️  Loading source image...")
image = load_image(f"{lib_root}/scaled/GymLady.jpeg").resize((1024, 1024))

print("🚀 Running inference...")
style_name = "Ghibli"
prompt = f"Turn this image into the {style_name} style."

result_image = pipeline(
    image=image, 
    prompt=prompt, 
    height=1024, 
    width=1024, 
    num_inference_steps=24
).images[0]

debug_dir = f"{lib_root}/debug_output"
os.makedirs(debug_dir, exist_ok=True)
output_filename = f"{debug_dir}/{style_name}_test.png"
result_image.save(output_filename)

print(f"✅ Image saved as {output_filename}")
print("👀 Check if the image has color (not black)!")
