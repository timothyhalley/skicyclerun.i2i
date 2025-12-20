# 📸 SkiCycleRun.i2i - Apple Photos to S3 with LoRA Artistic Processing

A complete photo processing pipeline that transforms Apple Photos exports into artistic variations using FLUX LoRA models, adds intelligent watermarks, and deploys to AWS S3. Built for batch processing large photo collections with multiple artistic styles.

**Pipeline Flow:**

```text
Apple Photos → Metadata Extract → Preprocess → LoRA Artistic Filters → Watermarking → AWS S3
```

---

## 🎯 Features

- **Apple Photos Integration** - Direct export from Apple Photos with album preservation
- **AI-Generated Watermarks** - Ollama LLM creates contextual watermarks from location, POI, and date metadata
- **Enhanced Geocoding** - 3-tier system (Photon → Google Maps → Nominatim) for accurate POI identification
- **Multi-LoRA Processing** - Apply 26+ artistic styles (Afremov, Gorillaz, Origami, PencilDrawing, etc.)
- **Comprehensive EXIF** - Captures 30+ metadata fields including lens info, GPS heading, and exposure settings
- **AWS S3 Deployment** - Automated upload with proper caching and content-type headers
- **Resume Capability** - Graceful stop/resume for long-running 10+ hour processes
- **Progress Tracking** - Real-time logging with per-image timing and batch progress

---

## 🚀 Quick Start

### 1. Environment Setup

**Required before every terminal session:**

```bash
# Set up environment variables
source ./env_setup.sh /Volumes/MySSD/skicyclerun.i2i /Volumes/MySSD/huggingface

# Verify setup
printenv SKICYCLERUN_LIB_ROOT
printenv HF_HOME
```

### 2. Run Pipeline

**Full pipeline (all stages):**

```bash
caffeinate -i python pipeline.py --yes
```

**Individual stages:**

```bash
# Export from Apple Photos
python pipeline.py --stages export

# Extract metadata and geocode
python pipeline.py --stages metadata_extraction geocode_sweep

# Process with LoRA styles
python pipeline.py --stages lora_processing

# Add watermarks
python pipeline.py --stages post_lora_watermarking

# Deploy to S3
python pipeline.py --stages s3_deployment
```

### 3. Graceful Shutdown & Resume

**Stop during long runs:**

```bash
# In another terminal
touch /tmp/skicyclerun_stop
```

**Resume processing:**

```bash
caffeinate -i python pipeline.py --stages lora_processing
# Automatically skips already-processed images
```

---

## 📂 Project Structure

```text
skicyclerun.i2i/
├── config/
│   ├── pipeline_config.json    # Unified pipeline & LoRA configuration
│   └── lora_registry.json      # 26 LoRA style definitions
├── core/
│   ├── lora_transformer.py     # LoRA processing engine (was main.py)
│   ├── pipeline_loader.py      # FLUX.1-Kontext-dev loader
│   ├── lora_manager.py         # LoRA loading (HuggingFace + local)
│   ├── image_processor.py      # Preprocessing & resizing
│   ├── inference_runner.py     # Image-to-image inference
│   ├── geo_extractor.py        # GPS & geocoding with caching
│   └── ollama_watermark.py     # AI watermark generation
├── utils/
│   ├── watermark.py            # Watermark application
│   ├── cli.py                  # Config loading utilities
│   └── logger.py               # Structured logging
├── pipeline.py                 # Main orchestrator (8 stages)
└── scripts/
    └── osxPhotoExporter.scpt   # AppleScript for Photos export
```

---

## ⚙️ Configuration

### Environment Variables

The `env_setup.sh` script exports:

```bash
SKICYCLERUN_LIB_ROOT      # Pipeline data root directory
HUGGINGFACE_CACHE_LIB     # HuggingFace model cache
HF_HOME                   # HuggingFace home directory
HUGGINGFACE_CACHE         # HuggingFace cache directory
HF_DATASETS_CACHE         # HuggingFace datasets cache
```

### Config Health Check

```bash
# Validate configuration and paths
python core/lora_transformer.py --check-config
python pipeline.py --check-config
```

### Pipeline Configuration

Edit `config/pipeline_config.json`:

```json
{
  "pipeline": {
    "stages": [
      "export",
      "cleanup",
      "metadata_extraction",
      "geocode_sweep",
      "preprocessing",
      "lora_processing",
      "post_lora_watermarking",
      "s3_deployment"
    ]
  },
  "ollama": {
    "enabled": true,
    "endpoint": "http://localhost:11434",
    "model": "llama3.2:3b",
    "timeout": 10,
    "fallback_on_error": true
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

---

## 📊 Pipeline Stages

### Stage 0: Cleanup

- Archive old outputs to timestamped zip files
- Prepare directories for new export
- **Output:** `{lib_root}/archive/pipeline_YYYYMMDD_HHMMSS.zip`

### Stage 1: Export

- AppleScript exports from Apple Photos
- Preserves album structure
- **Output:** `{lib_root}/albums/[AlbumName]/[images]`

### Stage 2: Metadata Extraction

- Extract 30+ EXIF fields (GPS, date, camera, lens, exposure)
- Reverse geocoding via Nominatim
- Cache results to avoid rate limits
- **Output:** `{lib_root}/metadata/master.json`

### Stage 3: Geocode Sweep

- Enhanced POI identification (Photon → Google Maps → Nominatim)
- AI watermark generation via Ollama LLM
- Nearby landmark enrichment
- **Updates:** `master.json` with `watermark_text`, `location`, `landmarks`

### Stage 4: Preprocessing

- Resize to 1024x1024 for LoRA input
- Convert to WebP format
- Optimize quality
- **Output:** `{lib_root}/pipeline/preprocessed/[AlbumName]/[images].webp`

### Stage 5: LoRA Processing

- Apply artistic style filters (FLUX.1-Kontext-dev)
- Process multiple LoRA styles per image
- MPS (Apple Silicon) or CUDA acceleration
- **Output:** `{lib_root}/pipeline/lora_processed/[AlbumName]/[Style]/[images]_[Style]_[timestamp].webp`

### Stage 6: Post-LoRA Watermarking

- Apply AI-generated watermarks from Ollama
- Embed copyright metadata in EXIF
- Preserve album structure
- **Output:** `{lib_root}/pipeline/watermarked_final/[AlbumName]/[Style]/[images].webp`

### Stage 7: S3 Deployment

- Upload to AWS S3 with public ACL
- Set cache headers (max-age=31536000)
- Content-Type: image/webp
- **Output:** `s3://skicyclerun.lib/albums/[AlbumName]/[images].webp`

---

## 🎨 LoRA Styles

### Featured Styles (26 total)

- **Afremov** - Leonid Afremov impressionist oil painting with palette knife texture
- **Gorillaz** - Jamie Hewlett-inspired cartoon-punk graphic style
- **PencilDrawing** - Fine pencil sketch with masterful shading
- **FractalGeometry** - Recursive geometric patterns
- **Super_Pencil** - Clean realistic pencil drawing
- **American_Comic** - Bold ink lines with vibrant colors
- **Origami** - Paper folding geometric style
- **Van_Gogh**, **Monet**, **Cezanne** - Impressionist masters

### List Available Styles

```bash
python core/lora_transformer.py --list-loras
```

### Registry Configuration

Each LoRA in `config/lora_registry.json` includes:

- Description and artistic style notes
- Custom prompts and negative prompts
- LoRA strength (0.6-0.9) and text encoder scale (0.4-0.7)
- Path (HuggingFace repo or local `.safetensors` file)

---

## 🧠 AI Watermark Generation

### How It Works

1. **Geocode Sweep Stage** calls Ollama LLM with metadata:

   - Location name and POI (e.g., "Pür & Simple, Kelowna")
   - Nearby landmarks from POI enrichment
   - Date taken and year
   - Camera model

2. **Ollama generates creative text**:

   - Examples: "Singapore Delights • January 2023", "Downtown Victoria • 2024"
   - Stored in `master.json` as `watermark_text`

3. **Watermarking stage applies text**:
   - Uses Ollama-generated text if present
   - Falls back to template: `SkiCycleRun © {year} {astro_symbol} {location}`
   - Embeds in EXIF copyright field

### Configuration

```json
{
  "ollama": {
    "enabled": true,
    "endpoint": "http://localhost:11434",
    "model": "llama3.2:3b",
    "timeout": 10,
    "fallback_on_error": true
  }
}
```

---

## 🔧 Requirements

### Python 3.13+

```bash
pip install torch torchvision diffusers transformers accelerate
pip install Pillow pillow-heif piexif
pip install geopy requests pytz
pip install boto3  # For S3 deployment
```

### Hardware

- **Apple Silicon (M1/M2/M3)** with MPS backend: ~11min/image
- **NVIDIA GPU with CUDA**: ~3-5min/image
- **CPU fallback**: ~45min/image (not recommended)

### Storage

- **Phase 1 (Export)**: ~500MB per 100 images
- **Phase 2 (LoRA)**: ~3GB per 100 images × 6 styles
- **Temp cache**: ~20GB for HuggingFace models

---

## 🧩 Developer Guide

### Stage Architecture Principles

**Immutability Rules:**

- Each stage has clearly defined input/output directories
- No stage may modify files outside its scope
- Stage interfaces (schema, filenames) are immutable once validated
- Downstream code adapts to upstream contracts, never vice versa

**Change Control:**

- Modifications to stable stages require documented rationale
- All changes logged in `CHANGELOG.md`
- Reproducibility tests required before merging

### Metadata Catalog

**Single Source of Truth:** `master.json`

Location: `{lib_root}/metadata/master.json`

Structure:

```json
{
  "/path/to/original/IMG_1234.jpg": {
    "file_name": "IMG_1234.jpg",
    "file_path": "/path/to/original/IMG_1234.jpg",
    "exif": { "date_taken": "2025-11-01T14:30:45" /* 30+ fields */ },
    "gps": { "lat": 39.7392, "lon": -104.9903 },
    "location": { "city": "Denver", "state": "Colorado" },
    "location_formatted": "Denver, CO",
    "watermark_text": "Denver Delights • November 2025",
    "landmarks": [
      /* nearby POIs */
    ],
    "pipeline": {
      "stages": ["metadata_extraction", "geocode_sweep"],
      "timestamps": {
        /* stage completion times */
      }
    }
  }
}
```

**Derived files** (preprocessed, LoRA variants) each get entries with `source_path` back-reference.

### File Naming Convention

```text
Original:     IMG_1234.HEIC
Preprocessed: IMG_1234.webp
LoRA Output:  IMG_1234_Afremov_20251109_143052.webp
              └─────┘ └─────┘ └──────────────┘
              base    LoRA    timestamp
Watermarked:  IMG_1234_Afremov_20251109_143052.webp (embedded EXIF)
S3 Path:      s3://skicyclerun.lib/albums/VacationAlbum/IMG_1234_Afremov_20251109_143052.webp
```

### Common Tasks

**List LoRA styles:**

```bash
python core/lora_transformer.py --list-loras
```

**Process single image:**

```bash
python core/lora_transformer.py --lora Anime --file photo.jpg
```

**Batch process album:**

```bash
python core/lora_transformer.py --lora Impressionism --batch \
  --input-folder ./data/preprocessed/VacationPhotos \
  --output-folder ./data/lora_processed
```

---

## 🐛 Troubleshooting

### Apple Photos Export Issues

- **Permission denied**: Grant Terminal.app Full Disk Access in System Settings → Privacy & Security
- **Test export**: `osascript scripts/osxPhotoExporter.scpt /tmp/test_export`
- **Album not found**: Check album name spelling in Photos app

### LoRA Processing Slow

- **M3 Max timing**: ~11 minutes 46 seconds per image
- **Graceful stop**: `touch /tmp/skicyclerun_stop` to exit cleanly
- **Resume**: Re-run same command - skips already-processed images
- **Check progress**: `tail -f logs/pipeline_YYYYMMDD_HHMMSS.log`

### Watermark Issues

- **Missing metadata**: Check `metadata/master.json` for location data
- **Location shows "Unknown"**: GPS data missing from EXIF
- **Ollama not running**: Start with `ollama serve` or disable in config

### Geocoding Rate Limits

- **Nominatim**: 1 request/second (automatically enforced)
- **Cache location**: `{lib_root}/metadata/geocode_cache.json`
- **Cache-only dev mode**: Add `--cache-only-geocode` flag to skip network calls

### S3 Deployment Failures

- **AWS credentials**: Ensure `~/.aws/credentials` configured
- **Bucket permissions**: Check S3 bucket policy allows PutObject
- **Test upload**: `aws s3 cp test.webp s3://skicyclerun.lib/albums/test.webp`

### Memory Issues

- **FLUX model size**: ~12GB GPU RAM required
- **Monitor**: Activity Monitor → GPU (Apple Silicon) or `nvidia-smi` (NVIDIA)
- **Clear cache**: Restart Python if memory accumulates

---

## ⏱️ Performance & Storage

### Processing Time (M3 Max, 48GB RAM)

- **Per image per LoRA**: ~11 minutes 46 seconds
- **79 images × 6 LoRAs**: ~155 hours theoretical (10-12 hours actual with optimizations)
- **Recommendation**: Use `caffeinate -i` to prevent sleep during long runs

### Storage Requirements

- **Raw Export**: ~500MB per 100 photos
- **LoRA Output**: ~3GB per 100 images × 6 styles
- **Total for 79 images**: ~2.4GB local + 2.4GB S3

### Optimization Tips

- **WebP format**: 30-40% smaller than JPEG with better quality
- **Cleanup stage**: Archives old outputs automatically
- **Selective LoRA**: Edit `loras_to_process` to run fewer styles initially
- **S3 lifecycle**: Configure lifecycle policy to archive to Glacier after 90 days

---

## 🔗 Quick Reference Commands

```bash
# Complete pipeline
caffeinate -i python pipeline.py --yes

# Resume from specific stage
python pipeline.py --stages lora_processing post_lora_watermarking s3_deployment

# Check S3 deployment
aws s3 ls s3://skicyclerun.lib/albums/ --recursive --human-readable

# Monitor logs
tail -f logs/pipeline_$(date +%Y%m%d)*.log

# Count output files
ls -1 "$SKICYCLERUN_LIB_ROOT/pipeline/lora_processed"/**/*.webp | wc -l

# Verify watermarks
find "$SKICYCLERUN_LIB_ROOT/pipeline/watermarked_final" -name "*.webp" | head -5 | xargs -I {} exiftool {} | grep -i copyright
```

---

## 🧑‍💻 Author

Built by **Tim Halley** for the SkiCycleRun photo collection - automating the transformation of family photos into artistic variations with intelligent metadata preservation and cloud deployment.

**Tech Stack:**

- FLUX.1-Kontext-dev (Black Forest Labs)
- PyTorch with MPS backend (Apple Silicon)
- HuggingFace Diffusers
- Ollama LLM (llama3.2:3b)
- AWS S3 + boto3
- Apple Photos AppleScript integration

**Links:**

- [FLUX Kontext Models](https://huggingface.co/Kontext-Style/models)
- [Black Forest Labs](https://huggingface.co/black-forest-labs)
- [Ollama](https://ollama.ai/)

---

## 📝 Related Documentation

- **REFACTOR_LORA_TRANSFORMER.md** - Details on main.py → core/lora_transformer.py refactoring
- **WORKFLOW.md** - Detailed workflow examples
- **config/lora_registry.json** - Complete LoRA style definitions
- **config/pipeline_config.json** - Pipeline configuration reference

---

**Last Updated:** December 6, 2025
