# SkiCycleRun Photo Processing Pipeline

Complete photo management pipeline: Apple Photos export → metadata extraction → watermarking → LoRA style processing

## Architecture

```
Apple Photos
    ↓
[Export Stage] → /Volumes/MySSD/ImageLib/input/[album_name]/
    ↓
[Cleanup Stage] → Archive old outputs
    ↓
[Metadata Extraction] → Extract GPS + Reverse Geocode
    ↓
[Preprocessing] → Scale & Optimize
    ↓
[Watermarking] → "SkiCycleRun © 2026 ♈ Denver, CO"
    ↓
[LoRA Processing] → Apply artistic style filters
    ↓
Final Output → /Volumes/MySSD/ImageLib/output/
```

## Quick Start

### 1. Full Pipeline (All Stages)

```bash
python pipeline.py
```

### 2. Specific Stages Only

```bash
# Export from Apple Photos only
python pipeline.py --stages export

# Metadata + Watermarking only
python pipeline.py --stages metadata_extraction watermarking

# Everything except export
python pipeline.py --stages cleanup metadata_extraction preprocessing watermarking lora_processing
```

### 3. LoRA Processing (After Pipeline)

```bash
# Process watermarked images through LoRA
python main.py --lora American_Comic --batch

# With custom seed for reproducibility
python main.py --lora Sketch --batch --seed 42

# Fine-tune LoRA strength
python main.py --lora Chinese_Ink --batch --lora-scale 0.6 --text-encoder-scale 0.4
```

## Configuration

Edit `config/pipeline_config.json` to customize:

### Paths

- `apple_photos_export`: Where to export from Photos app
- `raw_input`: Source images folder
- `preprocessed`: Scaled/optimized images
- `output`: Final processed images
- `metadata_catalog`: JSON catalog with GPS/location data

### Export Settings

```json
{
  "export": {
    "enabled": true,
    "format": "jpeg",
    "quality": 95,
    "preserve_albums": true
  }
}
```

### Geocoding Provider

```json
{
  "metadata_extraction": {
    "geocoding": {
      "provider": "nominatim",
      "api_url": "https://nominatim.openstreetmap.org/reverse",
      "rate_limit_seconds": 1.0,
      "cache_enabled": true
    }
  }
}
```

### Watermark Format

```json
{
  "watermark": {
    "format": "SkiCycleRun © {year} {astro_symbol} {location}",
    "year_offset": 1,
    "position": "bottom_right",
    "font": {
      "size": 24,
      "color": [255, 255, 255, 180],
      "stroke_width": 2
    }
  }
}
```

## New Modules

### `core/geo_extractor.py`

- Extracts GPS coordinates from EXIF
- Reverse geocodes using OpenStreetMap Nominatim
- Caches results to avoid API rate limits
- Returns: `{"city": "Denver", "state": "CO", "lat": 39.7392, "lon": -104.9903}`

### `core/watermark_generator.py`

- Calculates astrological symbol from date
- Formats watermark: `"SkiCycleRun © 2026 ♈ Denver, CO"`
- Supports all 12 zodiac symbols

### `core/watermark_applicator.py`

- Applies text overlay with PIL
- Configurable position (bottom_right, top_left, center, etc.)
- Stroke outline for readability
- Auto-scales font size based on image dimensions

### `scripts/osxPhotoExporter.scpt`

- AppleScript to export all Photos albums
- Creates organized folder structure
- Sanitizes album names for filesystem
- Progress logging every 10 photos

### `pipeline.py`

- Main orchestrator for all stages
- Loads config from JSON
- Maintains metadata catalog
- Can run individual stages

## Dependencies

Install required packages:

```bash
pip install Pillow requests
```

## Metadata Catalog

After `metadata_extraction` stage, check:

```
/Volumes/MySSD/ImageLib/metadata/catalog.json
```

Example entry:

```json
{
  "/Volumes/MySSD/ImageLib/input/Vacation/IMG_1234.jpg": {
    "file_name": "IMG_1234.jpg",
    "timestamp": "2025-11-05T16:30:00",
    "gps_coordinates": { "lat": 39.7392, "lon": -104.9903 },
    "location": {
      "city": "Denver",
      "state": "Colorado",
      "country": "United States"
    },
    "location_formatted": "Denver, Colorado"
  }
}
```

## LoRA Integration

The pipeline prepares images for LoRA processing. After watermarking, run:

```bash
# American comic style
python main.py --lora American_Comic --batch

# Pencil sketch (subtle)
python main.py --lora Super_Pencil --batch --lora-scale 0.65

# Reproduce exact output
python main.py --lora Origami --file input.jpg --seed 987654321
```

Check logs for seed values:

```
🎲 Seed: 1234567890
⚖️  LoRA strength - UNet: 0.85, Text Encoder: 0.65
💬 Prompt: c0m4i4, hand-drawn American comic style...
```

## Workflow Example

```bash
# 1. Export from Apple Photos
python pipeline.py --stages export

# 2. Extract metadata & apply watermarks
python pipeline.py --stages metadata_extraction watermarking

# 3. Apply LoRA style to watermarked images
python main.py --lora American_Cartoon --batch --seed 42

# 4. Check results
ls -lh /Volumes/MySSD/ImageLib/output/
```

## Troubleshooting

### Apple Photos Export

- Grant Terminal.app permissions in System Preferences → Security & Privacy → Automation
- Check: `osascript scripts/osxPhotoExporter.scpt /test/path`
- Example: `osascript scripts/osxPhotoExporter.scpt /Volumes/MySSD/ImageLib/input`

### Geocoding Rate Limits

- Nominatim: 1 request/second (configured automatically)
- Results are cached in `/Volumes/MySSD/ImageLib/metadata/geocode_cache.json`

### Missing GPS Data

- Not all photos have GPS coordinates
- Watermark will show "Unknown Location" if no GPS data found

### LoRA Style Consistency

- Lower `--lora-scale` for subtle effects (0.5-0.7)
- Higher for bold transformations (0.85-1.0)
- Use `--seed` for reproducible results
- Guidance scale now optimized at 3.5 (was 7.5)

## Next Steps

- [ ] Implement image preprocessing module (scaling, optimization)
- [ ] Add date extraction from EXIF for accurate astrological symbols
- [ ] Support multiple geocoding providers (Mapbox, HERE, Azure)
- [ ] Batch LoRA testing across all styles
- [ ] Ollama vision integration for intelligent prompt generation
