# 📸 SkiCycleRun.i2i - Apple Photos to S3 with LoRA Artistic Processing

A complete photo processing pipeline that transforms Apple Photos exports into artistic variations using FLUX LoRA models, adds intelligent watermarks, and deploys to AWS S3. Built for batch processing large photo collections with multiple artistic styles.

**Pipeline Flow:**
Apple Photos → Extract/Preprocess → LoRA Artistic Filters → Watermarking → AWS S3

---

## 🎯 Features

- **Apple Photos Integration** - Direct export from Apple Photos with album preservation
- **Intelligent Preprocessing** - EXIF extraction, geocoding, metadata cataloging
- **Multi-LoRA Processing** - Apply 6+ artistic styles (Afremov, Gorillaz, Origami, PencilDrawing, etc.)
- **Smart Watermarking** - Context-aware watermarks using location, date, and zodiac metadata
- **AWS S3 Deployment** - Automated upload with proper caching and content-type headers
- **Resume Capability** - Graceful stop/resume for long-running 10+ hour processes
- **Progress Tracking** - Real-time logging with per-image timing and batch progress

---

## 🚀 Quick Start

**Full Pipeline (Apple Photos → S3):**

```bash
caffeinate -i python pipeline.py
```

**Individual Stages:**

```bash
# Export from Apple Photos
python pipeline.py --stages export

# Process with LoRA styles
python pipeline.py --stages lora_processing

# Add watermarks
python pipeline.py --stages post_lora_watermarking

# Deploy to S3
python pipeline.py --stages s3_deployment
```

---

## 📂 Project Structure

```text
skicyclerun.i2i/
├── config/
│   ├── pipeline_config.json    # Main pipeline configuration
│   ├── lora_registry.json      # 26 LoRA style definitions
│   └── default_config.json     # Base processing config
├── core/
│   ├── pipeline_loader.py      # FLUX.1-Kontext-dev loader
│   ├── lora_manager.py         # LoRA loading (HuggingFace + local)
│   ├── image_processor.py      # Preprocessing & resizing
│   └── inference_runner.py     # Image-to-image inference
├── utils/
│   ├── watermark.py            # Watermark generation & application
│   └── logger.py               # Structured logging
├── pipeline.py                 # Main orchestrator (7 stages)
├── main.py                     # LoRA processing engine
├── postprocess_lora.py         # Watermarking with metadata lookup
└── scripts/
    └── osxPhotoExporter.scpt   # AppleScript for Photos export
```

---

## ⚙️ Configuration

### Pipeline Config (`config/pipeline_config.json`)

```json
{
  "pipeline": {
    "stages": [
      "export",
      "cleanup",
      "metadata_extraction",
      "preprocessing",
      "lora_processing",
      "post_lora_watermarking",
      "s3_deployment"
    ]
  },
  "lora_processing": {
    "loras_to_process": [
      "Afremov",
      "Gorillaz",
      "PencilDrawing",
      "FractalGeometry"
    ]
  },
  "s3_deployment": {
    "bucket_name": "skicyclerun.lib",
    "bucket_prefix": "albums"
  }
}
```

### LoRA Registry (`config/lora_registry.json`)

26 artistic styles including:

- **Afremov** - Impressionist palette knife oil painting
- **Gorillaz** - Cartoon-punk graphic novel aesthetic
- **PencilDrawing** - Fine pencil sketch with tonal shading
- **FractalGeometry** - Recursive mathematical patterns
- **Origami** - Paper folding geometric style
- And 21 more...

---

## 🧪 Pipeline Usage

**Full pipeline with caffeinate (prevents sleep):**

```bash
caffeinate -i python pipeline.py
```

**Specific stages:**

```bash
# Export from Apple Photos and preprocess
python pipeline.py --stages export metadata_extraction preprocessing

# Apply LoRA styles only
python pipeline.py --stages lora_processing

# Watermark processed images
python pipeline.py --stages post_lora_watermarking

# Deploy to S3
python pipeline.py --stages s3_deployment
```

**Single image LoRA test:**

```bash
python main.py --file input.webp --lora Afremov --output /tmp/test
```

**List available LoRA styles:**

```bash
python main.py --list-loras
```

---

For long-running batch processes (10+ hours), you can stop and resume processing:

**To stop gracefully:**

```bash
# In another terminal
touch /tmp/skicyclerun_stop
```

**What happens:**

- ✅ Current image completes processing (no corruption)
- ✅ Stop file auto-deletes after shutdown
- ✅ Logs timestamp, progress, and shutdown reason
- ✅ All files saved properly before exit

**To resume:**

```bash
python main.py --batch --lora <style>
```

**Resume features:**

- Automatically skips already-processed images
- Checks for `{basename}_{LoRA}_{timestamp}.webp` in output folder
- Continues with remaining images
- Works across pipeline restarts

**Startup check:**

- Warns if leftover stop file detected from interrupted run
- Auto-removes stale stop files
- Logs all stop/resume actions with timestamps

**Example log output:**

```text
🛑 STOP FILE DETECTED: /tmp/skicyclerun_stop
⏰ Stop requested at: 2025-11-09 05:30:45
📊 Progress: Completed 42/108 images
✅ Gracefully shutting down - current image processing will complete
💡 To resume: Run the same command again (already-processed images will be skipped)
🗑️  Stop file removed: /tmp/skicyclerun_stop
👋 Exiting gracefully at 2025-11-09 05:30:45
```

## 🛑 Graceful Shutdown & Resume

For long-running batch processes (10+ hours), you can stop and resume processing:

**To stop gracefully:**

```bash
# In another terminal
touch /tmp/skicyclerun_stop
```

**What happens:**

- ✅ Current image completes processing (no corruption)
- ✅ Stop file auto-deletes after shutdown
- ✅ Logs timestamp, progress, and shutdown reason
- ✅ All files saved properly before exit

**To resume:**

```bash
caffeinate -i python pipeline.py --stages lora_processing
```

**Resume features:**

- Automatically skips already-processed images
- Checks for `{basename}_{LoRA}_{timestamp}.webp` in output folder
- Continues with remaining images
- Works across pipeline restarts

**Example log output:**

```text
🛑 STOP FILE DETECTED: /tmp/skicyclerun_stop
⏰ Stop requested at: 2025-11-09 05:30:45
📊 Progress: Completed 42/108 images
✅ Gracefully shutting down - current image processing will complete
💡 To resume: Run the same command again (already-processed images will be skipped)
```

---

## 📊 Pipeline Stages

### Phase 1: Extract & Prepare

**Stage 1: export** - AppleScript exports from Apple Photos to raw folder

**Stage 2: metadata_extraction** - EXIF, GPS, geocoding (Nominatim) → catalog.json

**Stage 3: preprocessing** - Resize to 2048px, convert to WebP, optimize

**Output:** `/phase1_extract/scaled/[Album]/[images].webp`

### Phase 2: LoRA Processing

**Stage 4: lora_processing** - Apply artistic LoRA filters (6 styles × N images)

- Uses FLUX.1-Kontext-dev base model
- MPS (Apple Silicon) or CUDA acceleration
- ~11m 46s per image on M3 Max

**Output:** `/phase2_lora/processed/[Album]/IMG_####_[Style]_[timestamp].webp`

### Phase 2.5: Watermarking

**Stage 5: post_lora_watermarking** - Context-aware watermarks

- Looks up original metadata from Phase 1 catalog
- Format: `SkiCycleRun © 2015 ♏ Montreal, Quebec`
- Preserves album structure

**Output:** `/phase2_lora/watermarked/[Album]/IMG_####_[Style]_[timestamp].webp`

### Phase 3: Deployment

**Stage 6: s3_deployment** - Upload to AWS S3

- Bucket: `s3://skicyclerun.lib/albums/[AlbumName]/`
- Content-Type: `image/webp`
- Cache-Control: `max-age=31536000, public`
- Skips existing files (duplicate detection)

---

## 🎨 LoRA Styles

**Working LoRA Models:**

- **Afremov** - Leonid Afremov impressionist oil painting with palette knife texture
- **Gorillaz** - Jamie Hewlett-inspired cartoon-punk graphic style
- **PencilDrawing** - Fine pencil sketch with masterful shading and vintage etching
- **FractalGeometry** - Recursive geometric patterns with mathematical elegance
- **Super_Pencil** - Clean realistic pencil drawing with expressive shading
- **American_Comic** - Bold ink lines with vibrant flat colors and stylized shading

**Local LoRA Models:**

Stored in `/Volumes/MySSD/skicyclerun.i2i/models/lora/`:

- `afremov_flux_objects1.safetensors`
- `gorillaz-kontext-lora.safetensors`

**Registry Configuration:**

Each LoRA includes:

- Description and artistic style notes
- Custom prompts and negative prompts
- LoRA strength (0.6-0.9) and text encoder scale (0.4-0.7)
- Path (HuggingFace repo or local file)

---

## 🔧 Requirements

### Python 3.13+

```bash
pip install torch torchvision diffusers transformers
pip install Pillow piexif geopy requests
pip install boto3  # For S3 deployment
```

### Hardware

- Apple Silicon (M1/M2/M3) with MPS backend: ~11min/image
- NVIDIA GPU with CUDA: ~3-5min/image
- CPU fallback: ~45min/image (not recommended)

### Storage

- Phase 1: ~500MB per 100 images (WebP compressed)
- Phase 2: ~3GB per 100 images × 6 LoRA styles
- Temp cache: ~20GB for HuggingFace models

---

## 🧑‍💻 Author

Built by Tim Halley for the SkiCycleRun photo collection - automating the transformation of family photos into artistic variations with intelligent metadata preservation and cloud deployment.

**Tech Stack:**

- FLUX.1-Kontext-dev (Black Forest Labs)
- PyTorch with MPS backend (Apple Silicon)
- HuggingFace Diffusers
- AWS S3 + boto3
- Apple Photos AppleScript integration

**Links:**

- [FLUX Kontext Models](https://huggingface.co/Kontext-Style/models)
- [Black Forest Labs](https://huggingface.co/black-forest-labs)
