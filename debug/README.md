# Debug & Test Tools

Diagnostic scripts for troubleshooting pipeline issues.

## Master Store & Metadata

- **check_master_store.py** - Inspect master.json contents and entry count
- **test_watermark_metadata.py** - Test metadata lookup for LoRA images

## Image Processing

- **test_aspect_ratio.py** - Test aspect ratio calculations
- **test_scaling.py** - Test image scaling logic
- **test_preprocessor.py** - Test preprocessing stage

## LoRA & Inference

- **test_working_pattern.py** - Test LoRA inference pipeline
- **test_inference_memory.py** - Monitor memory usage during inference

## Watermarking

- **test_watermark.py** - Test watermark generation

---

**Note**: These are development/debugging tools. For production, use `pipeline.py` with appropriate `--stages` flags.
