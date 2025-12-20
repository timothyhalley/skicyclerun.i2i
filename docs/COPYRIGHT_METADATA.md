# Copyright Metadata Configuration

## Overview

The copyright metadata system embeds comprehensive copyright and metadata information directly into image EXIF data. This includes:

- **Copyright notice** with year and owner
- **Artist/Creator** information
- **Comprehensive description** with location, POI, GPS coordinates, date taken, camera info
- **Keywords** generated from location and landmarks
- **Website/UserComment** for attribution

## Configuration

Add to your `config/pipeline_config.json`:

```json
{
  "copyright": {
    "enabled": true,
    "owner": "SkiCycleRun",
    "website": "https://skicyclerun.com",
    "rights_statement": "Copyright © {year} {owner}. All rights reserved."
  }
}
```

### Configuration Options

| Field              | Type    | Default                                              | Description                         |
| ------------------ | ------- | ---------------------------------------------------- | ----------------------------------- |
| `enabled`          | boolean | `false`                                              | Enable copyright metadata embedding |
| `owner`            | string  | `"SkiCycleRun"`                                      | Copyright owner name                |
| `website`          | string  | `"https://skicyclerun.com"`                          | Website URL for attribution         |
| `rights_statement` | string  | `"Copyright © {year} {owner}. All rights reserved."` | Copyright text template             |

## What Gets Embedded

### EXIF Fields

The following EXIF fields are populated:

1. **Copyright** (IFD.Copyright)

   - Format: "Copyright © 2024 SkiCycleRun. All rights reserved."

2. **Artist** (IFD.Artist)

   - Format: "SkiCycleRun"

3. **ImageDescription** (IFD.ImageDescription)

   - Format: "Location: Kelowna, BC | Near: Pür & Simple | GPS: 49.887178, -119.426064 | Captured: January 15, 2023 at 10:44 AM | Camera: Apple iPhone 14 Pro | Lens: iPhone 14 Pro back triple camera 6.86mm f/1.78"

4. **XPKeywords** (IFD.XPKeywords)

   - Format: "SkiCycleRun;Kelowna;British Columbia;Canada;Pür & Simple;Photography;Travel;Adventure"

5. **UserComment** (Exif.UserComment)
   - Format: "https://skicyclerun.com"

## Example Output

When you embed copyright metadata, the image EXIF will contain:

```text
Copyright: Copyright © 2024 SkiCycleRun. All rights reserved.
Artist: SkiCycleRun
ImageDescription: Location: Kelowna, BC | Near: Pür & Simple | GPS: 49.887178, -119.426064 | Captured: January 15, 2023 at 10:44 AM | Camera: Apple iPhone 14 Pro | Lens: iPhone 14 Pro back triple camera 6.86mm f/1.78
XPKeywords: SkiCycleRun;Kelowna;British Columbia;Canada;Pür & Simple;Photography;Travel;Adventure
UserComment: https://skicyclerun.com
```

## Usage

### Automatic During Watermarking

Copyright metadata is automatically embedded during the `post_lora_watermarking` stage if enabled:

```bash
python pipeline.py --stages post_lora_watermarking --yes
```

### Verify Embedded Metadata

Check that copyright metadata was embedded:

```bash
# Using exiftool
exiftool image.webp | grep -E "Copyright|Artist|Description|Keywords"

# Using identify (ImageMagick)
identify -verbose image.webp | grep -E "Copyright|Artist|Description|Keywords"
```

### Python API

```python
from core.copyright_embedder import CopyrightEmbedder

# Initialize
config = {...}  # Your pipeline config
embedder = CopyrightEmbedder(config)

# Embed copyright metadata
metadata = {
    'location_formatted': 'Kelowna, BC',
    'gps_coordinates': {'lat': 49.887178, 'lon': -119.426064},
    'date_taken': '2023-01-15T10:44:17',
    'landmarks': [{'name': 'Pür & Simple'}],
    'exif': {
        'camera_make': 'Apple',
        'camera_model': 'iPhone 14 Pro',
        'lens_model': 'iPhone 14 Pro back triple camera 6.86mm f/1.78'
    }
}

success = embedder.embed_copyright_metadata(
    'input.webp',
    'output.webp',
    metadata
)

# Verify
verified = embedder.verify_copyright_metadata('output.webp')
print(verified['copyright'])
print(verified['description'])
```

## Dependencies

The copyright embedder requires the `piexif` library:

```bash
pip install piexif
```

## Benefits

1. **Legal Protection**: Copyright notice embedded directly in image file
2. **Attribution**: Clear artist/creator information
3. **Discoverability**: Keywords help with image search and organization
4. **Context**: Comprehensive description provides full context about the photo
5. **Proof of Ownership**: Embedded metadata travels with the image
6. **Professional**: Industry-standard EXIF fields for compatibility

## Compatibility

- **Supported Formats**: JPEG, PNG, WebP (any format supported by PIL and piexif)
- **Readers**: Compatible with Adobe Lightroom, Photoshop, macOS Preview, Windows Photo Viewer, exiftool, and other EXIF-aware software
- **Standards**: Uses standard EXIF/TIFF tags for maximum compatibility

## Notes

- Embedding happens AFTER watermarking to preserve both visual and metadata copyright
- Metadata is embedded in-place (modifies the output file)
- If embedding fails, the watermarked image is still saved (graceful fallback)
- GPS coordinates from original photo are preserved
- Date information uses DateTimeOriginal from EXIF when available
