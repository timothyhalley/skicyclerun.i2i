# FLUX Pipeline Fixes - Restoring Working Pattern

## Root Cause of Black Image

The black image was caused by several deviations from the proven working pattern:

### ❌ What Was Wrong

1. **Wrong dtype**: Using `float16` instead of `bfloat16`

   - FLUX requires `torch.bfloat16` for proper color output
   - Using float16 causes numerical instability → black images

2. **Complex LoRA loading**: Over-engineered with cache resolution

   - Simple Hub loading works best
   - Adapter name should be "lora" (not custom names)

3. **Image preprocessing**: Unnecessary rescaling and preprocessing

   - FLUX wants 1024x1024 directly
   - Additional preprocessing can corrupt the tensor

4. **Missing guidance_scale**: Working example doesn't use it
   - FLUX may handle this differently than other diffusion models

## ✅ What Was Fixed

### 1. Pipeline Loader (`core/pipeline_loader.py`)

```python
# OLD (broken):
pipeline = FluxKontextPipeline.from_pretrained(
    model_name,
    dtype=torch.float16,  # ❌ Wrong!
    ...
)

# NEW (working):
pipeline = FluxKontextPipeline.from_pretrained(
    model_name,
    torch_dtype=torch.bfloat16,  # ✅ Critical!
    cache_dir=cache_dir
).to(device)
```

### 2. LoRA Manager (`core/lora_manager.py`)

```python
# OLD (over-complicated):
pipeline.load_lora_weights(
    pretrained_model_name_or_path_or_dict=lora_config["path"],
    weight_name=lora_config["weights"],
    adapter_name=lora_config["adapter_name"],  # ❌ Custom name
    prefix=None,
    cache_dir=config["cache_dir"],
    local_files_only=False
)

# NEW (simple, working):
pipeline.load_lora_weights(
    lora_config["path"],
    weight_name=lora_config["weights"],
    adapter_name="lora"  # ✅ Simple name
)
pipeline.set_adapters(["lora"], adapter_weights=[1.0])
```

### 3. Image Processor (`core/image_processor.py`)

```python
# OLD (complex rescaling):
image = rescale_image(image, max_dim)  # ❌ Aspect ratio logic
if preprocess_cfg.get("enabled", False):
    image = preprocess_image(image, preprocess_cfg)

# NEW (simple, direct):
image = load_image(path)
image = image.resize((1024, 1024), Image.LANCZOS)  # ✅ Direct resize
```

### 4. Inference Runner (`core/inference_runner.py`)

```python
# OLD (used guidance_scale):
result = pipeline(
    image,  # ❌ Positional
    prompt=prompt,
    negative_prompt=negative_prompt,  # ❌ May not work with FLUX
    num_inference_steps=steps,
    guidance_scale=guidance,  # ❌ May cause issues
    height=height,
    width=width
)

# NEW (matching working example):
result = pipeline(
    image=image,  # ✅ Explicit parameter
    prompt=prompt,
    height=1024,
    width=1024,
    num_inference_steps=24  # ✅ Working value
)
```

### 5. Config (`config/pipeline_config.json` → `lora_processing`)

```json
// OLD:
"precision": "float16",  // ❌ Wrong!
"num_inference_steps": 12,  // ❌ Too few

// NEW:
"precision": "bfloat16",  // ✅ Required for FLUX
"num_inference_steps": 24,  // ✅ Working value
```

## Testing

Run the test script to verify:

```bash
python test_working_pattern.py
```

This uses the EXACT pattern from your working code and should produce a colored Ghibli image.

Then test the LoRA transformer:

```bash
python core/lora_transformer.py
```

## Key Takeaways

1. **FLUX is picky about precision** - must use bfloat16
2. **Simpler is better** - the working code was minimal for a reason
3. **Don't over-engineer** - Hub loading works perfectly
4. **1024x1024 is optimal** - FLUX is designed for this size
5. **Trust the working example** - when something works, stick close to it!
