# IMAGE SCALE GUIDE

This guide documents how image dimensions are determined from preprocessing through LoRA inference and final output.

## Quick answer

- Standard LoRA feed size uses `lora_processing.max_dim`, currently `1024`.
- Aspect ratio is preserved.
- Width/height are rounded to multiples of `16` before inference.
- Final generated image size matches the prepared inference size.

## Stage-by-stage sizing flow

### Stage 4: Preprocessing (catalog pre-scale)

Purpose:

- Normalize and optimize source images before LoRA processing.

Rules:

- `preprocessing.max_dimension` is currently `2048`.
- If an image is already within 2048 x 2048, original dimensions are kept.
- If larger, it is scaled down to fit within 2048 while preserving aspect ratio.
- Dimensions are rounded down to multiples of `8`.

Typical result:

- A preprocessed image with max side up to 2048, ready for downstream processing.

### Stage 6: LoRA preparation before inference

Purpose:

- Prepare preprocessed images for FLUX LoRA inference.

Rules:

- Input is read from the preprocessed folder.
- `lora_processing.max_dim` is currently `1024`.
- Longest side is resized to `1024`.
- Short side is computed from aspect ratio.
- Both dimensions are rounded to multiples of `16`.

Typical result:

- Inference input size has long side = 1024 and both sides divisible by 16.

## Standard sizes fed to LoRA

There is not one fixed size. Standard sizes are an aspect-ratio-preserving family with long side 1024 and multiple-of-16 rounding.

Common examples:

- 1024 x 1024
- 1024 x 768
- 1024 x 640
- 1024 x 576
- 1024 x 512

Exact short side depends on each source image aspect ratio.

## Final output size

Inference is called with explicit `width` and `height` taken from the prepared image.

Therefore:

- Final LoRA output dimensions equal prepared inference dimensions.
- No additional resize is applied when saving the generated image.

## Exception modes

### low_memory mode

Overrides:

- `max_dim = 512`
- `num_inference_steps = 12`
- `precision = float16`

### tiny_mode

Overrides:

- `max_dim = 256`
- `num_inference_steps = 8`
- `precision = float16`

In these modes, the same aspect-ratio + multiple-of-16 behavior applies, but with a smaller long side.

## Important note about the 512-cap helper

There is a separate helper that caps to 512, but the active LoRA path uses `load_and_prepare_image` (the 1024-based path by default), not that capped helper.

## Config values currently driving this behavior

- `preprocessing.max_dimension = 2048`
- `lora_processing.max_dim = 1024`
- `lora_processing.preprocess.enabled = true`
- `lora_processing.preprocess.cleanup = true`
- `lora_processing.preprocess.face_detection = false`
