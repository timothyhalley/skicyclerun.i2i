# SkiCycleRun Image (I2I) Processing Workflow

## Overview

Three-phase pipeline for processing photos from Apple Photos through LoRA artistic filters to AWS S3 deployment.

---

## Folder Structure

```text
/Volumes/MySSD/ImageLib/
│
├── phase1_extract/              # PHASE 1: Extract & Prepare
│   ├── raw/                     # Apple Photos exports (by album)
│   │   └── [AlbumName]/         # One folder per album
│   │       └── IMG_*.jpg        # Original exports with EXIF/GPS
│   ├── scaled/                  # Preprocessed images (2048px max)
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

- `phase2_lora/processed/[AlbumName]/[StyleName]/` - Styled images organized by album and style

### Configuration

File: `config/default_config.json`

```json
{
  "input_folder": "/Volumes/MySSD/ImageLib/phase1_extract/watermarked",
  "output_folder": "/Volumes/MySSD/ImageLib/phase2_lora/processed"
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
python main.py --lora American_Comic --batch
```

#### Single Style - Specific Album

```bash
python main.py --lora Impressionism --batch --input /Volumes/MySSD/ImageLib/phase1_extract/watermarked/VacationPhotos
```

#### Single Style - Single Image

```bash
python main.py --lora Van_Gogh --input /Volumes/MySSD/ImageLib/phase1_extract/watermarked/AlbumName/image.webp
```

#### Custom Seed (Reproducibility)

```bash
python main.py --lora Monet --batch --seed 42
```

#### Override LoRA Strength

```bash
python main.py --lora LEGO --batch --lora-scale 0.9 --text-encoder-scale 0.7
```

### Batch Processing Strategy

Process each album with multiple styles:

```bash
# Album: VacationPhotos with 3 styles
for style in American_Comic Impressionism Watercolor; do
  python main.py --lora $style --batch --input /Volumes/MySSD/ImageLib/phase1_extract/watermarked/VacationPhotos
done
```

### Output Organization

```text
phase2_lora/processed/
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

- `phase2_lora/processed/` - LoRA-processed images

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
```

---

## Configuration Files

### `config/pipeline_config.json`

Phase 1 pipeline settings:

- Folder paths
- Geocoding provider (Nominatim)
- Watermark format and font
- Preprocessing settings (max size, quality)

### `config/default_config.json`

Phase 2 LoRA processing settings:

- Input/output folders
- FLUX model settings (steps, guidance scale)
- Device settings (MPS, bfloat16)
- Cache directories

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
