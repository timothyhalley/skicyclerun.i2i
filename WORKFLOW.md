# SkiCycleRun Image (I2I) Processing Workflow

## Overview

Three-phase pipeline for processing photos from Apple Photos through LoRA artistic filters to AWS S3 deployment.

---

## Prerequisites

### 1. Environment Setup

Set up required environment variables before running the pipeline:

```bash
source ./env_setup.sh /Volumes/MySSD/skicyclerun.i2i
```

This sets:

- `SKICYCLERUN_LIB_ROOT` - Pipeline data root directory
- `HUGGINGFACE_CACHE_LIB` / `HF_HOME` - HuggingFace model cache location

### 2. Python Environment

Ensure Python has blake2 hash support (required by HuggingFace libraries):

```bash
# Test blake2 support
python -c "import hashlib; print('blake2b:', hashlib.blake2b); print('✅ blake2 working!')"
```

If blake2 is not working, reinstall Python with proper OpenSSL support:

```bash
bash fix_python_blake2.sh
```

### 3. HuggingFace Authentication

**Required for downloading LoRA models from HuggingFace Hub.**

#### Check if logged in:

```bash
hf auth whoami
```

#### If not logged in:

1. **Get your HuggingFace token:**
   - Visit: https://huggingface.co/settings/tokens
   - Create a new token with `read` permissions
   - Copy the token

2. **Log in:**

   ```bash
   hf auth login
   ```

   - Paste your token when prompted
   - Choose `Y` to save as git credential (optional but recommended)

3. **Verify authentication:**
   ```bash
   hf auth whoami
   ```
   Should display: `user: YourUsername`

#### Token Location

Your token is saved to:

- `~/.huggingface/token` (primary location)
- `$HF_HOME/token` (if `HF_HOME` is set)
- macOS Keychain (if you said yes to git credential)

#### Notes

- The pipeline will automatically check for HuggingFace authentication before running LoRA processing
- If `local_files_only: false` in config, models will be downloaded from HuggingFace Hub
- Downloaded models are cached in `$HUGGINGFACE_CACHE_LIB` for future use
- After first download, you can set `local_files_only: true` to use cached models only

---

## Folder Structure

```text
{lib_root}/
│
├── phase1_extract/              # PHASE 1: Extract & Prepare
│   ├── albums/                  # Apple Photos exports (by album)
│   │   └── [AlbumName]/         # One folder per album
│   │       └── IMG_*.jpg        # Original exports with EXIF/GPS
│   ├── scaled/                  # Preprocessed images (1024px max)
│   │   └── [AlbumName]/         # Album structure preserved
│   │       └── image.webp       # Optimized WebP format
│   ├── watermarked/             # Watermarked images (ready for LoRA)
│   │   └── [AlbumName]/         # Album structure preserved
│   │       └── location_name.webp  # Smart-named with watermarks
│   └── metadata/
│       └── catalog.json         # Complete metadata catalog
│
├── phase2_lora/                 # PHASE 2: LoRA Artistic Processing
│   ├── processed/               # LoRA-processed images
│   │   └── [AlbumName]/         # Album structure preserved
│   │       └── [StyleName]/     # Organized by LoRA style
│   │           └── location_name.webp
│   └── batch_logs/              # Processing logs and reports
│
├── phase3_deploy/               # PHASE 3: AWS S3 Ready (Future)
│   └── [AlbumName]/             # Final organized albums
│       └── [StyleName]/         # Ready for web consumption
│           └── optimized images
│
└── archive/                     # Archived old outputs
    └── [timestamp]/             # Date-stamped archives
```

---

## Phase 1: Extract & Prepare

**Purpose**: Extract photos from Apple Photos, add metadata, watermark, and prepare for artistic processing.

### Phase 1 Input

- Apple Photos albums (selected via dialog)

### Phase 1 Output

- `phase1_extract/watermarked/[AlbumName]/` - Watermarked images ready for LoRA

### Steps

1. **Export from Apple Photos**

   ```bash
   python pipeline.py --stages export
   ```

   - Runs AppleScript to export selected albums
   - Preserves GPS/EXIF metadata
   - Output: `phase1_extract/raw/[AlbumName]/`

2. **Extract Metadata & Geocode**

   ```bash
   python pipeline.py --stages metadata_extraction
   ```

   - Extracts GPS coordinates from EXIF
   - Reverse geocodes to location names (Nominatim)
   - Extracts date taken for zodiac symbols
   - Output: `phase1_extract/metadata/catalog.json`

3. **Preprocess Images**

   ```bash
   python pipeline.py --stages preprocessing
   ```

   - Scales to max 2048px (preserves aspect ratio)
   - Converts to WebP (quality 90)
   - Ensures dimensions are multiples of 8 (FLUX requirement)
   - Preserves album folder structure
   - Output: `phase1_extract/scaled/[AlbumName]/`

4. **Apply Watermarks**

   ```bash
   python pipeline.py --stages watermarking
   ```

   - Applies: `SkiCycleRun © 2026 ♍️ Montreal, Quebec`
   - Zodiac symbol based on photo date taken
   - Asimovian font with emoji support
   - Smart renaming (IMG_1234 → montreal_quebec_1234)
   - Skips location text if GPS unavailable (keeps © and symbol)
   - Output: `phase1_extract/watermarked/[AlbumName]/`

### Run All Phase 1 Steps

```bash
python pipeline.py --stages export metadata_extraction preprocessing watermarking
```

### Idempotency

All stages check for existing output and skip duplicates:

- Metadata extraction: Skips images already cataloged
- Preprocessing: Skips images already scaled
- Watermarking: Skips images already watermarked

---

## Phase 2: LoRA Artistic Processing

**Purpose**: Apply artistic LoRA style filters to watermarked images.

### Phase 2 Input

- `phase1_extract/watermarked/[AlbumName]/` - Watermarked images from Phase 1

### Phase 2 Output

- `images/lora_processed/[AlbumName]/[StyleName]/` - Styled images organized by album and style

### Configuration

File: `config/pipeline_config.json` → `lora_processing`

```json
{
  "input_folder": "{lib_root}/images/scaled",
  "output_folder": "{lib_root}/images/lora_processed",
  "num_inference_steps": 24,
  "guidance_scale": 3.5,
  "precision": "bfloat16"
}
```

### Available LoRA Styles

26 styles in `config/lora_registry.json`:

- American_Comic, American_Cartoon, Anime, Chinese_Ink
- Impressionism, Cubism, Van_Gogh, Monet
- LEGO, Clay_Animation, Pixel_Art, Watercolor
- And 14 more...

### Processing Commands

#### Single Style - All Images

```bash
python core/lora_transformer.py --lora American_Comic --batch
```

#### Single Style - Specific Album

```bash
python core/lora_transformer.py --lora Impressionism --batch --input "$SKICYCLERUN_LIB_ROOT/images/watermarked/VacationPhotos"
```

#### Single Style - Single Image

```bash
python core/lora_transformer.py --lora Van_Gogh --input "$SKICYCLERUN_LIB_ROOT/images/watermarked/AlbumName/image.webp"
```

#### Custom Seed (Reproducibility)

```bash
python core/lora_transformer.py --lora Monet --batch --seed 42
```

#### Override LoRA Strength

```bash
python core/lora_transformer.py --lora LEGO --batch --lora-scale 0.9 --text-encoder-scale 0.7
```

### Batch Processing Strategy

Process each album with multiple styles:

```bash
# Album: VacationPhotos with 3 styles
for style in American_Comic Impressionism Watercolor; do
  python core/lora_transformer.py --lora $style --batch --input "$SKICYCLERUN_LIB_ROOT/images/watermarked/VacationPhotos"
done
```

### Output Organization

```text
images/lora_processed/
  VacationPhotos/
    American_Comic/
      paris_001.webp
      london_002.webp
    Impressionism/
      paris_001.webp
      london_002.webp
    Watercolor/
      paris_001.webp
      london_002.webp
```

---

## Phase 3: AWS S3 Deployment (Future)

**Purpose**: Prepare final organized albums for web consumption.

### Phase 3 Input

- `images/lora_processed/` - LoRA-processed images

### Phase 3 Output

- `phase3_deploy/` - Final structure ready for S3 sync
- S3 bucket organized by album and style

### Planned Steps

1. Final optimization for web delivery
2. Generate thumbnails and responsive sizes
3. Create album manifests (JSON metadata)
4. Sync to S3 with proper cache headers
5. Update CloudFront distribution

### Future Commands (TBD)

```bash
# Prepare for deployment
python prepare_deploy.py --album VacationPhotos

# Sync to S3
aws s3 sync phase3_deploy/ s3://skicyclerun-images/ --delete

# Invalidate CloudFront cache
aws cloudfront create-invalidation --distribution-id XXX --paths "/*"

aws cloudfront list-distributions --query "DistributionList.Items[*].[Id,DomainName,Origins.Items[0].DomainName,Comment]" --output table
-----------------------------------------------------------------------------------------------------------------
|                                               ListDistributions                                               |
+----------------+---------------------------------+----------------------------------------------+-------------+
|  E1SKA6PEPTIDW2|  ddiutukjt0tac.cloudfront.net   |  skicyclerun.tst.s3.us-west-2.amazonaws.com  |  DEV & TEST |
|  EG2MWPWJ56AVU |  d1pmfnhh6vq1hp.cloudfront.net  |  skicyclerun.com.s3.us-west-2.amazonaws.com  |  WWW PROD   |
|  E1GQ61X0LT69AR|  dph8i1b9tv95y.cloudfront.net   |  skicyclerun.lib.s3.us-west-2.amazonaws.com  |  PHOTO LIB  |
+----------------+---------------------------------+----------------------------------------------+-------------+

aws cloudfront create-invalidation --distribution-id E1GQ61X0LT69AR --paths "/*"


aws cloudfront list-distributions --output json | python3 -c "
import sys, json
data = json.load(sys.stdin)
items = data.get('DistributionList', {}).get('Items', [])
if not items:
    print('No CloudFront distributions found')
else:
    for dist in items:
        print(f\"ID: {dist['Id']}\")
        print(f\"Domain: {dist['DomainName']}\")
        origin = dist['Origins']['Items'][0]['DomainName']
        print(f\"Origin: {origin}\")
        print(f\"Status: {dist['Status']}\")
        print('---')
"

 aws cloudfront list-invalidations --distribution-id E1GQ61X0LT69AR --output table
```

---

## Configuration Files

### `config/pipeline_config.json`

Phase 1 pipeline settings:

- Folder paths
- Geocoding provider (Nominatim)
- Watermark format and font
- Preprocessing settings (max size, quality)

### `config/lora_registry.json`

LoRA style definitions:

- 26 artistic styles
- Per-style prompts and negative prompts
- Fine-tuned strength values (lora_scale, text_encoder_scale)

---

## Key Features

### Smart Filename Generation

- Generic names (IMG_1234) → Location-based (montreal_quebec_1234)
- Preserves meaningful original names
- Adds counters for duplicates (\_1, \_2, etc.)

### Watermark Intelligence

- Uses photo date taken for zodiac symbol (not current date)
- Skips location if GPS unavailable (keeps © and symbol)
- Asimovian font with emoji fallback for symbols
- Dynamic year offset (configurable)

### Album Organization

- Preserves album structure through all phases
- Each phase maintains folder hierarchy
- Easy to track images from source to final output

### Idempotent Operations

- Safe to re-run any stage without duplicates
- Checks existing output before processing
- Merges metadata catalogs intelligently

### Seed Reproducibility

- Auto-generates and logs seed for each LoRA run
- Can override with `--seed` for exact reproduction
- Uses torch.Generator for deterministic output

---

## Monitoring & Logs

### Pipeline Logs

```bash
logs/pipeline_[timestamp].log
```

### LoRA Processing Logs

```bash
phase2_lora/batch_logs/
  batch_[timestamp].log
  seed_tracking.json
```

### Metadata Catalog

```bash
phase1_extract/metadata/catalog.json
```

Contains:

- GPS coordinates and geocoded locations
- Original and processed image sizes
- File size reduction percentages
- Processing timestamps
- EXIF date taken

---

## Time Standard

- Standard: ISO8601 UTC with `Z` suffix for all pipeline-generated timestamps.
- Helper: `utils/time_utils.utc_now_iso_z()` is the single source for generating UTC timestamps.
- Applies to stored fields:
  - `master.json` → `created_at`, `pipeline.timestamps[stage]`
  - Preprocessing → `processed_timestamp`
  - Metadata extraction → `timestamp`
  - Watermarking → `watermark.applied_at`
  - S3 deployment → `deployment.uploaded_at`
- EXIF `date_taken` and derived UTC:
  - `date_taken`: preserved from file as-is (often naive/local time).
  - `date_taken_utc`: derived when GPS coordinates exist by inferring timezone via `timezonefinder` and converting local capture time to UTC. Stored with `Z`.
  - If inference is not possible (no GPS or lib missing), only `date_taken` is stored.
  - Downstream uses `date_taken_utc` preferentially for filenames and watermarks.

Dependencies

- Python stdlib `zoneinfo` for timezone conversions
- `timezonefinder` (added to `requirements.txt`) for lat/lon → timezone mapping

---

## Troubleshooting

### No GPS Data

- Ensure Photos app exports with metadata: `with metadata and GPS`
- Check EXIF: `exiftool image.jpg | grep GPS`
- Watermark will show: `SkiCycleRun © 2026 ♍️` (without location)

### LoRA Output Quality

- Adjust guidance_scale (default 3.5, try 1.0-5.0)
- Tune per-style lora_scale in registry (0.65-0.9)
- Increase num_inference_steps (default 24, try 28-32)

### File Size Too Large

- Reduce preprocessing max_dimension (default 2048)
- Lower WebP quality (default 90, try 85)

### Pipeline Re-run Issues

- Clear specific folder to force re-processing:
  - `rm -rf phase1_extract/scaled/AlbumName`
  - `rm -rf phase1_extract/watermarked/AlbumName`
- Or use archive cleanup: `python pipeline.py --stages cleanup`

---

## Next Steps

1. ✅ Complete Phase 1 pipeline
2. 🔄 Batch process albums through Phase 2 LoRA styles
3. 🔜 Design Phase 3 S3 deployment structure
4. 🔜 Build album manifest generator
5. 🔜 Implement CloudFront CDN integration
