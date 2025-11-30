# SkiCycleRun Photo Processing Pipeline

Complete photo management pipeline with numbered stages for clear output tracking.

## Directory Structure

```text
$SKICYCLERUN_LIB_ROOT/
└── pipeline/
    ├── archive/              # Stage 0: Archive old work before new export
    │   ├── albums/           # Old albums moved here
    │   │   ├── 2024-01-Paris/
    │   │   └── 2024-06-Tokyo/
    │   └── metadata/         # Versioned metadata backups
    │       ├── master_v1_20250101.json
    │       └── master_v2_20250115.json
    │
    ├── albums/               # Stage 1: NEW albums from Apple Photos
    │   ├── 2025-01-NewYork/  # ⚠️ Never re-export same album!
    │   └── 2025-03-London/
    │
    ├── metadata/             # Stage 2: Extracted metadata
    │   ├── master.json
    │   └── geocode_cache.json
    │
    ├── scaled/               # Stage 3: Preprocessed for LoRA
    │   ├── 2025-01-NewYork/
    │   └── 2025-03-London/
    │
    ├── lora_processed/       # Stage 4: LoRA-styled images
    │   ├── 2025-01-NewYork/
    │   └── 2025-03-London/
    │
    └── watermarked_final/    # Stage 5: Ready for S3
        ├── 2025-01-NewYork/
        └── 2025-03-London/
```

## Pipeline Stages

### Stage 0: Archive (Before New Export)

**Purpose**: Move old albums to archive before exporting new ones.

```bash
python pipeline.py --stages cleanup
```

**Operations**:
- Move `pipeline/albums/*` → `pipeline/archive/albums/`
- Version `pipeline/metadata/master.json` → `pipeline/archive/metadata/master_v{N}_{timestamp}.json`

### Stage 1: Export from Apple Photos

**Purpose**: Export NEW albums to `pipeline/albums/`.

**⚠️ CRITICAL**: Only select NEW albums. Re-exporting duplicates photos!

```bash
osascript scripts/osxPhotoExporter.scpt
```

**Output**: `$SKICYCLERUN_LIB_ROOT/pipeline/albums/[album_name]/`

### Stage 2: Metadata Extraction

**Purpose**: Extract EXIF, GPS, and geocode locations.

```bash
python pipeline.py --stages metadata_extraction
```

**Output**: `pipeline/metadata/master.json`

### Stage 3: Preprocessing

**Purpose**: Scale images for LoRA (max 1024x1024).

```bash
python pipeline.py --stages preprocessing
```

**Output**: `pipeline/scaled/[album_name]/*.webp`

### Stage 4: LoRA Processing

**Purpose**: Apply artistic style transformations.

```bash
caffeinate -i python pipeline.py --stages lora_processing
```

**Output**: `pipeline/lora_processed/[album_name]/*_{style}_{timestamp}.webp`

**Performance**: ~11-12 min per image per style (M3 Max)

### Stage 5: Watermarking

**Purpose**: Add location watermarks.

```bash
python pipeline.py --stages post_lora_watermarking
```

**Format**: `SkiCycleRun © 2026 ▲ Denver, CO`

**Output**: `pipeline/watermarked_final/[album_name]/*.webp`

### Stage 6: S3 Deployment

**Purpose**: Upload to AWS S3.

```bash
python pipeline.py --stages s3_deployment
```

**Output**: `s3://skicyclerun.lib/albums/[album_name]/`

## Quick Start

```bash
# 1. Setup environment (required in every terminal)
source ./env_setup.sh /Volumes/MySSD/skicyclerun.i2i /Volumes/MySSD/models

# 2. Archive old albums
python pipeline.py --stages cleanup

# 3. Export NEW albums from Apple Photos
osascript scripts/osxPhotoExporter.scpt

# 4. Run full pipeline
caffeinate -i python pipeline.py --yes

# 5. Verify S3
aws s3 ls s3://skicyclerun.lib/albums/ --recursive
```

## Configuration

Edit `config/pipeline_config.json`:

```json
{
  "paths": {
    "pipeline_base": "{lib_root}/pipeline",
    "archive_albums": "{pipeline_base}/archive/albums",
    "archive_metadata": "{pipeline_base}/archive/metadata",
    "apple_photos_export": "{pipeline_base}/albums",
    "metadata_dir": "{pipeline_base}/metadata",
    "preprocessed": "{pipeline_base}/scaled",
    "lora_processed": "{pipeline_base}/lora_processed",
    "watermarked_final": "{pipeline_base}/watermarked_final"
  }
}
```

## Troubleshooting

### Duplicate Photos
**Cause**: Re-exported same album  
**Fix**: Run Stage 0 (cleanup) before new exports

### Missing Watermark Location
**Cause**: No GPS in EXIF  
**Fix**: Enable in Photos → Settings → Include location

### Out of Memory
**Fix**: Automatic aggressive cleanup + resume capability

### S3 Upload Fails
**Fix**: Verify AWS credentials: `aws configure list`

## Performance (M3 Max, 48GB RAM)

| Stage | Time (79 images) |
|-------|------------------|
| Export | ~1 min |
| Metadata | ~3 min |
| Preprocessing | ~4 min |
| LoRA (5 styles) | ~70 hours |
| Watermarking | ~3 min |
| S3 Upload | ~7 min |

**Total**: ~70 hours (mostly LoRA processing)

## Related Files

- `config/pipeline_config.json` - Pipeline configuration
- `config/lora_registry.json` - LoRA style definitions
- `scripts/osxPhotoExporter.scpt` - Apple Photos export
- `main.py` - LoRA processing engine (Stage 4)
- `postprocess_lora.py` - Watermarking (Stage 5)
