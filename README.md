# 📸 SkiCycleRun.i2i - Apple Photos to S3 with LoRA Artistic Processing

A complete photo processing pipeline that transforms Apple Photos exports into artistic variations using FLUX LoRA models, adds intelligent watermarks, and deploys to AWS S3. Built for batch processing large photo collections with multiple artistic styles.

**Pipeline Flow:**

```text
Apple Photos → Metadata Extract → LLM Analysis → Preprocess → LoRA Artistic Filters → Watermarking → AWS S3
```

---

## 🎯 Features

- **Dual Interface** - Native macOS UI (`main.py`) or powerful CLI (`pipeline.py`)
- **Apple Photos Integration** - Direct export from Apple Photos with album preservation
- **6-Stage LLM Image Analysis** - Ollama-powered scene understanding, style detection, and contextual watermark generation
- **Enhanced Geocoding** - 3-tier system (Photon → Google Maps → Nominatim) for accurate POI identification
- **Multi-LoRA Processing** - Apply 26+ artistic styles (Afremov, Gorillaz, Origami, PencilDrawing, etc.)
- **Comprehensive EXIF** - Captures 30+ metadata fields including lens info, GPS heading, and exposure settings
- **AWS S3 Deployment** - Automated upload with proper caching and content-type headers
- **Resume Capability** - Graceful stop/resume for long-running 10+ hour processes
- **Progress Tracking** - Real-time logging with per-image timing and batch progress

---

## 🚀 Quick Start

### Choose Your Interface

**🖥️ Native macOS UI (Recommended for Interactive Use):**

```bash
# Launch graphical interface
python3 main.py
```

- ✅ Visual stage selection with checkboxes
- ✅ Real-time output streaming
- ✅ Live command preview
- ✅ Start/Stop controls
- ✅ No command-line memorization needed

**⌨️ Command Line (Recommended for Automation/Scripts):**

```bash
# Full pipeline automation
./run_Pipeline.sh --yes
```

---

## 🖥️ Setup & Run (CLI)

The project is CLI-only. Use the setup runner once, then execute pipeline stages directly.

---

## ⌨️ Using the CLI (pipeline.py)

### 1. Environment Setup

```bash
./run_SetupEnv.sh --profile performance/macmini-fast-20260326.txt
```

This configures Python, installs requirements into the pinned interpreter, writes `.env`, and updates config defaults.

### 2. Run Complete Pipeline

**Full pipeline (all stages):**

```bash
./run_Pipeline.sh --yes
```

### 3. Run Individual Stages

```bash
# Export from Apple Photos
./run_Pipeline.sh --stages export

# Extract metadata and analyze with LLM
./run_Pipeline.sh --stages metadata_extraction llm_image_analysis

# Process with LoRA styles
./run_Pipeline.sh --stages lora_processing

# Add watermarks
./run_Pipeline.sh --stages post_lora_watermarking

# Deploy to S3
./run_Pipeline.sh --stages s3_deployment
```

### 4. Graceful Shutdown & Resume

**Stop during long runs:**

```bash
# In another terminal
touch /tmp/skicyclerun_stop
```

**Resume processing:**

```bash
./run_Pipeline.sh --stages lora_processing
# Automatically skips already-processed images
```

---

## 📂 Project Structure

```text
skicyclerun.i2i/
├── main.py                     # 🖥️ Native macOS UI entry point
├── pipeline.py                 # ⌨️ CLI orchestrator (8 stages)
├── config/
│   ├── pipeline_config.json    # Unified pipeline & LoRA configuration
│   └── lora_registry.json      # 26 LoRA style definitions
├── ui/                         # Native macOS UI components
│   ├── app.py                  # UI application coordinator
│   ├── models/                 # Config parsing & command building
│   ├── controllers/            # Pipeline subprocess execution
│   └── views/                  # Native Cocoa windows & controls
├── core/                       # Pipeline processing engines
│   ├── lora_transformer.py     # LoRA artistic style processing
│   ├── llm_image_analyzer.py   # 6-stage Ollama image analysis
│   ├── pipeline_loader.py      # FLUX.1-Kontext-dev model loader
│   ├── lora_manager.py         # LoRA loading (HuggingFace + local)
│   ├── image_processor.py      # Preprocessing & resizing
│   ├── inference_runner.py     # Image-to-image inference
│   ├── geo_extractor.py        # GPS & geocoding with caching
│   └── ollama_watermark.py     # AI watermark generation
├── utils/
│   ├── watermark.py            # Watermark application
│   ├── cli.py                  # Config loading utilities
│   └── logger.py               # Structured logging
└── scripts/
    └── osxPhotoExporter.scpt   # AppleScript for Photos export
```

**Entry Points:**

- **`main.py`** → Launches native macOS UI with visual controls
- **`pipeline.py`** → Executes pipeline stages via command line

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

All stages can be run via **UI** (check boxes) or **CLI** (--stages flag).

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

### Stage 3: LLM Image Analysis

- **6-stage Ollama-powered analysis:**
  1. **Scene Understanding** - Objects, setting, composition
  2. **Style Detection** - Color palette, lighting, artistic qualities
  3. **Geocoding Enhancement** - POI identification with 3-tier fallback
  4. **Location Enrichment** - Nearby landmarks and cultural context
  5. **Watermark Generation** - Creative text based on scene + location
  6. **Quality Assessment** - Technical evaluation (blur, exposure, etc.)
- Structured JSON output with confidence scores
- **Updates:** `master.json` with `watermark_text`, `llm_analysis`, `location`, `landmarks`

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

## 🧠 LLM Image Analysis (6-Stage Ollama Pipeline)

### How It Works

The `llm_image_analysis` stage uses Ollama to perform comprehensive image understanding:

#### Stage 1: Scene Understanding

- Analyzes objects, people, setting, and composition
- Detects activity and context
- **Output:** Structured scene description

#### Stage 2: Style Detection

- Identifies color palette, lighting, and mood
- Detects artistic qualities and photographic techniques
- **Output:** Style attributes with confidence scores

#### Stage 3: Geocoding Enhancement

- 3-tier POI identification:
  1. **Photon API** (OpenStreetMap-based, fast)
  2. **Google Maps Places API** (fallback, high accuracy)
  3. **Nominatim** (final fallback)
- Uses GPS coordinates from EXIF
- **Output:** Location name, address, place type

#### Stage 4: Location Enrichment

- Queries nearby landmarks and attractions
- Adds cultural/historical context
- **Output:** Array of nearby POIs with distances

#### Stage 5: Watermark Generation

- Creates contextual watermark text combining:
  - Location name and POI (e.g., "Pür & Simple, Kelowna")
  - Date taken and year
  - Creative formatting
- **Examples:**
  - "Singapore Delights • January 2023"
  - "Downtown Victoria • 2024"
  - "Kelowna Adventures • Summer 2025"
- **Output:** `watermark_text` stored in `master.json`

#### Stage 6: Quality Assessment

- Technical evaluation (blur, exposure, composition)
- Identifies potential issues
- **Output:** Quality metrics and recommendations

### Configuration

Edit `config/pipeline_config.json`:

```json
{
  "ollama": {
    "enabled": true,
    "endpoint": "http://localhost:11434",
    "model": "llama3.2:3b",
    "timeout": 30,
    "fallback_on_error": true
  },
  "llm_image_analysis": {
    "enabled": true,
    "analyze_existing": false,
    "batch_size": 10
  }
}
```

### CLI Flags

```bash
# Force re-analysis of already-analyzed images
python3 pipeline.py --stages llm_image_analysis --force-llm-reanalysis

# Cache-only geocoding (skip network requests)
python3 pipeline.py --stages llm_image_analysis --cache-only-geocode

# Debug LLM prompts and responses
python3 pipeline.py --stages llm_image_analysis --debug-prompt --verbose
```

---

## 🔧 Requirements

### Python 3.13+

**Core Dependencies:**

```bash
pip install torch torchvision diffusers transformers accelerate
pip install Pillow pillow-heif piexif
pip install geopy requests pytz
pip install boto3  # For S3 deployment
```

**UI Dependencies (for main.py):**

```bash
pip install -r requirements-ui.txt
# Installs PyObjC for native macOS UI
```

### External Services

- **Ollama** - Run locally for LLM image analysis

  ```bash
  # Install Ollama
  brew install ollama

  # Start server
  ollama serve

  # Pull model
  ollama pull llama3.2:3b
  ```

- **AWS CLI** - Configure for S3 deployment

  ```bash
  aws configure
  # Enter: AWS Access Key ID, Secret Access Key, Region (us-west-2)
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

### Entry Points

**Main UI (main.py):**

- Launches native macOS application using PyObjC
- Coordinates UI components (models, views, controllers)
- Executes `pipeline.py` as subprocess
- Streams output to UI console
- **Usage:** Interactive pipeline execution with visual feedback

**Pipeline CLI (pipeline.py):**

- Core stage orchestration engine
- Handles 8 pipeline stages sequentially
- Loads configuration from `config/pipeline_config.json`
- Manages graceful shutdown via `/tmp/skicyclerun_stop`
- **Usage:** Automation, scripting, headless execution

### Architecture Principles

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

**Launch UI:**

```bash
python3 main.py
# Opens native macOS window with visual controls
```

**Run complete pipeline (CLI):**

```bash
caffeinate -i python3 pipeline.py --yes
```

**List LoRA styles:**

```bash
python3 core/lora_transformer.py --list-loras
```

**Process single image with LoRA:**

```bash
python3 core/lora_transformer.py --lora Anime --file photo.jpg
```

**Batch process album with LoRA:**

```bash
python3 core/lora_transformer.py --lora Impressionism --batch \
  --input-folder ./data/preprocessed/VacationPhotos \
  --output-folder ./data/lora_processed
```

**Run specific stages (CLI):**

```bash
# Metadata extraction and LLM analysis only
python3 pipeline.py --stages metadata_extraction llm_image_analysis

# LoRA processing with verbose output
python3 pipeline.py --stages lora_processing --verbose

# Force watermark regeneration
python3 pipeline.py --stages post_lora_watermarking --force-watermark
```

---

## 🐛 Troubleshooting

### UI Issues

**PyObjC import error:**

```bash
# Install PyObjC dependencies
pip3 install -r requirements-ui.txt

# Verify installation
python3 -c "import Cocoa; print('✅ PyObjC installed successfully')"
```

**UI window not showing:**

- Ensure running on macOS (PyObjC is macOS-only)
- Check Terminal has accessibility permissions in System Settings
- Try `python3 main.py --config config/pipeline_config.json`

**Pipeline not starting from UI:**

- Verify `pipeline.py` exists in project root
- Check `config/pipeline_config.json` is valid JSON
- Review output console for specific error messages

### CLI/Pipeline Issues

**Apple Photos Export Issues:**

- **Permission denied**: Grant Terminal.app Full Disk Access in System Settings → Privacy & Security
- **Test export**: `osascript scripts/osxPhotoExporter.scpt /tmp/test_export`
- **Album not found**: Check album name spelling in Photos app

**LoRA Processing Slow:**

- **M3 Max timing**: ~11 minutes 46 seconds per image
- **Graceful stop**: `touch /tmp/skicyclerun_stop` to exit cleanly
- **Resume**: Re-run same command - skips already-processed images
- **Check progress**: `tail -f logs/pipeline_YYYYMMDD_HHMMSS.log`

**LLM Analysis Issues:**

- **Ollama not running**: Start with `ollama serve` or disable in config
- **Model not found**: `ollama pull llama3.2:3b`
- **Timeout errors**: Increase `ollama.timeout` in config
- **Debug prompts**: Use `--debug-prompt --verbose` flags

**Geocoding Rate Limits:**

- **Nominatim**: 1 request/second (automatically enforced)
- **Cache location**: `{lib_root}/metadata/geocode_cache.json`
- **Cache-only mode**: Use `--cache-only-geocode` flag

**S3 Deployment Failures:**

- **AWS credentials**: Ensure `~/.aws/credentials` configured
- **Bucket permissions**: Check S3 bucket policy allows PutObject
- **Test upload**: `aws s3 cp test.webp s3://skicyclerun.lib/albums/test.webp`

**Memory Issues:**

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

**UI:**

```bash
# Launch native macOS UI
python3 main.py

# Launch with custom config
python3 main.py --config path/to/config.json
```

**CLI:**

```bash
# Complete pipeline
caffeinate -i python3 pipeline.py --yes

# Resume from specific stage
python3 pipeline.py --stages lora_processing post_lora_watermarking s3_deployment

# Force LLM re-analysis
python3 pipeline.py --stages llm_image_analysis --force-llm-reanalysis

# Verbose output with debug prompts
python3 pipeline.py --stages llm_image_analysis --verbose --debug-prompt
```

**Monitoring:**

```bash
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

- **UI**: PyObjC (native macOS Cocoa)
- **Pipeline**: Python 3.13 with modular stage architecture
- **AI Models**:
  - FLUX.1-Kontext-dev (Black Forest Labs) for image-to-image
  - Ollama llama3.2:3b for LLM image analysis
- **ML Framework**: PyTorch with MPS backend (Apple Silicon)
- **Libraries**: HuggingFace Diffusers, Pillow, geopy
- **Cloud**: AWS S3 + boto3
- **Integration**: Apple Photos AppleScript

**Links:**

- [FLUX Kontext Models](https://huggingface.co/Kontext-Style/models)
- [Black Forest Labs](https://huggingface.co/black-forest-labs)
- [Ollama](https://ollama.ai/)
- [PyObjC Documentation](https://pyobjc.readthedocs.io/)

---

## 📝 Related Documentation

- **ui/README.md** - Detailed UI architecture and component documentation
- **REFACTOR_LORA_TRANSFORMER.md** - Details on main.py → core/lora_transformer.py refactoring
- **WORKFLOW.md** - Detailed workflow examples
- **config/lora_registry.json** - Complete LoRA style definitions
- **config/pipeline_config.json** - Pipeline configuration reference
- **LLM_IMAGE_ANALYSIS_REFACTOR.md** - 6-stage LLM analysis architecture

---

**Last Updated:** December 20, 2025
