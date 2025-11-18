# SkiCycleRun Photo Processing Pipeline

Complete photo management pipeline: Apple Photos export → metadata extraction → LoRA style processing → watermarking → AWS S3 deployment

## Architecture

```text
Apple Photos
  ↓
[1. Export Stage] → {lib_root}/raw/[album_name]/
  ↓
[2. Cleanup Stage] → Archive old outputs, prepare directories under {lib_root}
  ↓
[3. Metadata Extraction] → Extract EXIF, GPS + Reverse Geocode + Dates → {lib_root}/metadata
  ↓
[4. Preprocessing] → Scale & Optimize for LoRA input → {lib_root}/scaled
  ↓
[5. LoRA Processing] → Apply artistic style filters → {lib_root}/images/lora_processed
  │    (Afremov, Gorillaz, PencilDrawing, FractalGeometry, etc.)
  ↓
[6. Post-LoRA Watermarking] → "SkiCycleRun © 2026 ♈ Denver, CO" → {lib_root}/images/lora_final
  │    (Applied AFTER LoRA to avoid style interference)
  ↓
[7. S3 Deployment] → Upload to AWS S3 bucket (source {lib_root}/images/lora_final)
    ↓
Final Output → s3://skicyclerun.lib/albums/
```

**Key Change**: Watermarking moved to Stage 6 (after LoRA) because LoRA models were obscuring/transforming watermarks applied in preprocessing.

## Quick Start

> Setup reminder: `source ./env_setup.sh <images_root> [huggingface_cache]` in every terminal. The script exports Hugging Face's `HF_HOME`, `HUGGINGFACE_CACHE`, and `HF_DATASETS_CACHE` to the SSD cache you specify, and explicitly unsets the deprecated `TRANSFORMERS_CACHE` variable to silence the warning. `pipeline.py` now runs the config health check automatically and pauses for confirmation before any work starts. Pass `--yes` for unattended runs.

### 1. Full Pipeline (All 7 Stages)

```bash
# Run complete pipeline with caffeinate to prevent sleep
caffeinate -i python pipeline.py --yes
```

### 2. Geocode Sweep (fill missing locations)

```bash
# Fill in locations for entries with GPS but missing location
python pipeline.py --stages geocode_sweep

# Force cache-only during dev (no network calls) or disable to sweep:
#   - Dev (fast):    python pipeline.py --stages metadata_extraction --cache-only-geocode
#   - Sweep (full):  python pipeline.py --stages geocode_sweep
```

### 3. Resume After LoRA Processing

```bash
# You've completed lora_processing, now run watermarking and S3:
python pipeline.py --stages post_lora_watermarking s3_deployment
```

### 4. Individual Stage Testing

```bash
# Export from Apple Photos only
python pipeline.py --stages export

# LoRA processing only (main processing step)
python pipeline.py --stages lora_processing

# Watermark LoRA output
python pipeline.py --stages post_lora_watermarking

# Deploy to S3
python pipeline.py --stages s3_deployment
```

### 5. Graceful Shutdown During Long Runs

```bash
# In another terminal while pipeline is running:
touch /tmp/skicyclerun_stop

# Pipeline will complete current image and exit cleanly
# Resume later with same command - already-processed images are skipped
```

### 6. Config Health Check

Validate that every stage directory and dependency is reachable before launching a long run:

```bash
python pipeline.py --config config/pipeline_config.json --check-config
```

This resolves `{lib_root}` placeholders, creates any missing folders (empty), and reports optional files like metadata catalogs so you can populate them in advance.

## Configuration

Edit `config/pipeline_config.json` to customize:

### Complete Stage Configuration

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
  }
}
```

### LoRA Processing Settings

```json
{
  "lora_processing": {
    "enabled": true,
    "loras_to_process": [
      "Afremov",
      "Gorillaz",
      "PencilDrawing",
      "FractalGeometry",
      "Super_Pencil",
      "American_Comic"
    ],
    "input_dir": "{lib_root}/images/scaled",
    "output_dir": "{lib_root}/images/lora_processed",
    "default_lora_scale": 0.85,
    "default_text_encoder_scale": 0.65,
    "guidance_scale": 3.5,
    "num_inference_steps": 28
  }
}
```

### Post-LoRA Watermark Format

```json
{
  "post_lora_watermarking": {
    "enabled": true,
    "input_dir": "{lib_root}/images/lora_processed",
    "metadata_catalog": "{lib_root}/images/metadata/master.json",
    "format": "SkiCycleRun © {year} {astro_symbol} {location}",
    "position": "bottom_right",
    "font": {
      "size": 36,
      "color": [255, 255, 255, 200],
      "stroke_width": 3,
      "stroke_color": [0, 0, 0, 255]
    }
  }
}
```

### Watermark Landmark Inclusion (Optional)

- To append a nearby relevant landmark to the watermark (e.g., “ — Royal BC Museum”):

```json
{
  "watermark": {
    "include_landmark": true,
    "landmark_min_score": 0.6,
    "landmark_max_distance_m": 300,
    "landmark_format": " — {name}"
  },
  "metadata_extraction": {
    "poi_enrichment": { "enabled": true }
  }
}
```

- Relevance is enforced using camera heading (when present) and distance caps to avoid noise.
- If no landmark passes thresholds, nothing is appended and the watermark remains unchanged.

### S3 Deployment Settings

```json
{
  "s3_deployment": {
    "enabled": true,
    "bucket_name": "skicyclerun.lib",
    "bucket_prefix": "albums",
    "region": "us-west-2",
    "content_type": "image/webp",
    "cache_control": "public, max-age=31536000",
    "acl": "public-read"
  }
}
```

## Key Modules

### Stage-Specific Components

#### `core/geo_extractor.py`

- Extracts GPS coordinates from EXIF metadata
- Reverse geocodes using OpenStreetMap Nominatim API
- Caches results to avoid rate limits
- Returns: `{"city": "Denver", "state": "CO", "lat": 39.7392, "lon": -104.9903}`

#### `core/image_preprocessor.py`

- Scales images for LoRA input (1024x1024 target)
- Maintains aspect ratio with padding
- Optimizes format (JPEG/WebP)

#### `core/pipeline_loader.py`

- Loads FLUX.1-Kontext-dev base model
- Initializes diffusion pipeline
- Manages GPU memory allocation

#### `core/lora_manager.py`

- Loads LoRA weights from HuggingFace or local paths
- Handles both `path` and `repo_id` formats
- Configures LoRA scale and text encoder scale

#### `core/inference_runner.py`

- Runs image-to-image inference with LoRA
- Applies artistic style transformations
- Manages seed for reproducibility

#### `postprocess_lora.py`

- Post-LoRA watermarking script
- Looks up metadata from catalog.json
- Calculates zodiac symbols from photo dates
- Applies watermark with PIL: `"SkiCycleRun © 2026 ♈ Denver, CO"`

#### `scripts/osxPhotoExporter.scpt`

- AppleScript for batch export from Apple Photos
- Creates organized folder structure by album
- Sanitizes album names for filesystem compatibility
- Progress logging every 10 photos

### Pipeline Orchestrator

#### `pipeline.py`

- Main coordinator for all 7 stages
- Loads config from `pipeline_config.json`
- Maintains metadata catalog across stages
- Can run individual stages via `--stages` argument
- Supports resume capability (skips already-processed images)

## Dependencies

Install required packages:

```bash
# Core dependencies
pip install torch torchvision diffusers transformers accelerate

# Image processing
pip install Pillow pillow-heif

# AWS deployment
pip install boto3

# Metadata & geocoding
pip install requests pytz

# Optional: Development tools
pip install pytest black flake8
```

## Quick Reference Commands

```bash
# Complete pipeline (all 7 stages)
caffeinate -i python pipeline.py

# Resume from where you left off
python pipeline.py --stages lora_processing post_lora_watermarking s3_deployment

# Watermark + S3 only (after LoRA is done)
python pipeline.py --stages post_lora_watermarking s3_deployment

# Graceful shutdown during long run
touch /tmp/skicyclerun_stop

# Check S3 deployment
aws s3 ls s3://skicyclerun.lib/albums/ --recursive --human-readable

# Monitor logs
tail -f logs/pipeline_$(date +%Y%m%d)*.log

# Check output count
ls -1 "$SKICYCLERUN_LIB_ROOT/images/lora_processed"/*.webp | wc -l

# Verify watermarks applied
find "$SKICYCLERUN_LIB_ROOT/images/lora_processed" -name "*_Afremov_*.webp" | head -5 | xargs -I {} identify -verbose {} | grep -i comment
```

## File Naming Convention

```text
Original:     IMG_1234.HEIC
Preprocessed: IMG_1234.jpg
LoRA Output:  IMG_1234_Afremov_20251109_143052.webp
              └─────┘ └─────┘ └──────────────┘
              base    LoRA    timestamp
Watermarked:  IMG_1234_Afremov_20251109_143052.webp (same, modified in-place)
S3 Path:      s3://skicyclerun.lib/albums/VacationAlbum/IMG_1234_Afremov_20251109_143052.webp
```

## Related Documentation

- **README.md** - Project overview, features, installation
- **config/lora_registry.json** - All 26 LoRA style definitions
- **config/pipeline_config.json** - Pipeline configuration
- **main.py** - Direct LoRA processing script (used internally by Stage 5)

## Metadata Catalog

Single source of truth:

- `master.json` (authoritative): incrementally updated by every stage and keyed by absolute file path.
  - Location: `{lib_root}/images/metadata/master.json` (see `paths.master_catalog`)
  - Contains per-file blocks: `exif`, `gps`, `location`, `preprocessing`, `watermark`, `lora`, `deployment`, and `pipeline` stage timestamps.

After `metadata_extraction`, entries appear in `master.json` keyed by the original image path:

```json
{
  "{lib_root}/images/raw/Vacation/IMG_1234.jpg": {
    "file_name": "IMG_1234.jpg",
    "file_path": "{lib_root}/images/raw/Vacation/IMG_1234.jpg",
    "extracted_timestamp": "2025-11-05T16:30:00",
    "exif": { "date_taken": "2025-11-01T14:30:45" },
    "gps": { "lat": 39.7392, "lon": -104.9903 },
    "location": { "city": "Denver", "state": "Colorado", "country": "United States" },
    "location_formatted": "Denver, CO",
    "pipeline": { "stages": ["metadata_extraction"], "timestamps": {"metadata_extraction": "..."} }
  }
}

Derived files (preprocessed, watermarked, LoRA variants) each get their own entries keyed by their absolute paths and include a `source_path` back-reference.
```

## Workflow Example: Complete Pipeline

### Scenario: Process 79 photos with 6 LoRA styles, watermark, and deploy to S3

```bash
# Step 1: Full pipeline (can take 10+ hours for 79 photos × 6 styles)
caffeinate -i python pipeline.py

# OR run stages individually:

# Step 2: Export from Apple Photos
python pipeline.py --stages export

# Step 3: Extract metadata (GPS, dates, locations)
python pipeline.py --stages metadata_extraction

# Step 4: Preprocess for LoRA (resize, optimize)
python pipeline.py --stages preprocessing

# Step 5: Apply all LoRA styles (longest stage ~11min 46sec per image on M3 Max)
python pipeline.py --stages lora_processing

# Step 6: Add watermarks to LoRA output
python pipeline.py --stages post_lora_watermarking

# Step 7: Deploy to S3
python pipeline.py --stages s3_deployment

# Check S3 bucket
aws s3 ls s3://skicyclerun.lib/albums/ --recursive | head -20
```

### Resume After Interruption

```bash
# If you stopped during lora_processing, just re-run:
python pipeline.py --stages lora_processing

# The pipeline will skip already-processed images automatically
# Check logs for: "✓ Already processed, skipping..."
```

### Output Structure

After complete pipeline:

```text
{lib_root}/images/lora_processed/
├── IMG_1234_Afremov_20251109_143052.webp
├── IMG_1234_Gorillaz_20251109_144238.webp
├── IMG_1234_PencilDrawing_20251109_145312.webp
├── IMG_1234_FractalGeometry_20251109_150445.webp
├── IMG_1234_Super_Pencil_20251109_151523.webp
└── IMG_1234_American_Comic_20251109_152617.webp

S3 Bucket (after deployment):
s3://skicyclerun.lib/albums/
├── Vacation2024/IMG_1234_Afremov_20251109_143052.webp
├── Vacation2024/IMG_1234_Gorillaz_20251109_144238.webp
└── ... (all watermarked variants)
```

## Troubleshooting

### Apple Photos Export Issues

- **Permission denied**: Grant Terminal.app Full Disk Access in System Settings → Privacy & Security → Full Disk Access
- **Test export**: `osascript scripts/osxPhotoExporter.scpt /tmp/test_export`
- **Album not found**: Check album name spelling in Photos app

### LoRA Processing Slow/Hanging

- **M3 Max timing**: ~11 minutes 46 seconds per image (79 images × 6 styles = 10+ hours)
- **Graceful stop**: `touch /tmp/skicyclerun_stop` to exit cleanly after current image
- **Resume**: Re-run same command - already-processed images are automatically skipped
- **Check progress**: `tail -f logs/pipeline_YYYYMMDD_HHMMSS.log`

### Watermark Not Visible

- **Why post-LoRA?**: LoRA models were obscuring watermarks applied before processing
- **Current approach**: Watermarks applied AFTER LoRA in Stage 6 (post_lora_watermarking)
- **Missing metadata**: If location shows "Unknown Location", GPS data not in EXIF
- **Test watermark**: Check `metadata/catalog.json` for location data

### S3 Deployment Failures

- **AWS credentials**: Ensure `~/.aws/credentials` configured with access key
- **Bucket permissions**: Check S3 bucket policy allows PutObject
- **Test upload**: `aws s3 cp test.webp s3://skicyclerun.lib/albums/test.webp --acl public-read`
- **CloudFront**: May need to invalidate cache after deployment

### Geocoding Rate Limits

- **Nominatim**: 1 request/second (automatically enforced)
- **Cache location**: `{lib_root}/images/metadata/geocode_cache.json`
- **Missing GPS**: Not all photos have GPS coordinates - watermark shows "Unknown Location"
- **Cache-only dev mode**: Skip network calls when building metadata for speed.
  - Toggle via config: `metadata_extraction.geocoding.cache_only: true`
  - Or per-run CLI: add `--cache-only-geocode` to pipeline command
  - Trade-offs: New coordinates won’t be resolved until a later full/sweep run; use for fast dev loops.

### POI Enrichment (Landmarks) — Optional

- Disabled by default to avoid noise; opt-in via:

```json
"metadata_extraction": {
  "poi_enrichment": {
    "enabled": true,
    "radius_m": 600,
    "max_results": 5,
    "categories": ["museum","attraction","viewpoint","historic","natural"],
    "use_heading_filter": true,
    "fov_degrees": 60,
    "max_distance_m": 500
  }
}
```

- Relevance filters to keep results aligned with the actual shot:
  - Category allowlist (e.g., museum/attraction/viewpoint/historic/natural).
  - Distance cap (`max_distance_m`) so far-away features are excluded.
  - Heading-cone filter (`use_heading_filter` + `fov_degrees`) to keep only POIs within the camera’s field-of-view.
- Stored in `master.json` under `landmarks` with name, category, distance, bearing, and optional `wikidata`.

### Memory Issues

- **FLUX model size**: ~12GB GPU RAM required
- **Monitor**: `nvidia-smi` (NVIDIA) or Activity Monitor → GPU (Apple Silicon)
- **Batch size**: Pipeline processes one image at a time to manage memory
- **Clear cache**: Restart Python if memory accumulates over long runs

## Performance & Storage

### Processing Time (M3 Max, 48GB RAM)

- **Per image per LoRA**: ~11 minutes 46 seconds
- **79 images × 6 LoRAs**: ~9,340 minutes (155 hours / 6.5 days theoretical)
- **Actual with overhead**: ~10-12 hours with parallel optimizations
- **Recommendation**: Use `caffeinate -i` to prevent sleep during long runs

### Storage Requirements

- **Phase 1 (Export)**: ~500MB per 100 photos (JPEG from Apple Photos)
- **Phase 2 (LoRA Output)**: ~3GB per 100 images × 6 styles (WebP format)
- **Phase 3 (Watermarked)**: Same size as Phase 2 (in-place modification)
- **Phase 4 (S3)**: Same as Phase 3 (cloud storage)
- **Total for 79 images**: ~2.4GB local, 2.4GB S3

### Optimization Tips

- **WebP format**: 30-40% smaller than JPEG with better quality
- **Cleanup stage**: Archives old outputs to save space
- **S3 lifecycle**: Configure S3 lifecycle policy to archive to Glacier after 90 days
- **Selective LoRA**: Edit `loras_to_process` to run fewer styles initially

## Next Steps After LoRA Processing

You mentioned you're ready to queue up the final steps. Here's your path forward:

### 1. Watermark All LoRA Output

```bash
# Apply watermarks to all LoRA-processed images in output directory
python pipeline.py --stages post_lora_watermarking

# This reads metadata from {lib_root}/images/metadata/master.json
# Generates watermarks like: "SkiCycleRun © 2026 ♈ Denver, CO"
# Processes all files matching: *_{LoRA}_{timestamp}.webp
```

### 2. Deploy to S3

```bash
# Upload all watermarked images to S3 bucket
python pipeline.py --stages s3_deployment

# Uploads to: s3://skicyclerun.lib/albums/
# Sets: Cache-Control: public, max-age=31536000
# Sets: ACL: public-read
# Content-Type: image/webp
```

### 3. Verify Deployment

```bash
# List uploaded files
aws s3 ls s3://skicyclerun.lib/albums/ --recursive | wc -l

# Should show: 79 images × 6 LoRAs = 474 files

# Check public URL (example):
open https://skicyclerun.lib.s3.amazonaws.com/albums/Vacation2024/IMG_1234_Afremov_20251109_143052.webp
```

### 4. CloudFront Distribution (Optional)

If you have CloudFront configured:

```bash
# Invalidate cache to show new images
aws cloudfront create-invalidation \
  --distribution-id YOUR_DISTRIBUTION_ID \
  --paths "/albums/*"
```

## Configuration Check Before Final Stages

Verify these settings in `config/pipeline_config.json`:

```json
{
  "post_lora_watermarking": {
    "enabled": true,
    "input_dir": "{lib_root}/images/lora_processed"
  },
  "s3_deployment": {
    "enabled": true,
    "bucket_name": "skicyclerun.lib",
    "bucket_prefix": "albums",
    "acl": "public-read"
  }
}
```
