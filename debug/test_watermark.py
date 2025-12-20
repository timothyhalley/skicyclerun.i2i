#!/usr/bin/env python3
"""
Test Watermark Script
Test watermarking on a single image with updated location formatting and font size

Usage:
    python test_watermark.py --file input.webp --output output_watermarked.webp
    python test_watermark.py --file input.webp --output output_watermarked.webp --location "Denver, CO"
"""
import argparse
import json
from pathlib import Path
from datetime import datetime
from core.watermark_generator import WatermarkGenerator
from core.watermark_applicator import WatermarkApplicator
from core.geo_extractor import GeoExtractor
from utils.logger import logInfo, logError


def test_watermark(
    input_file: str,
    output_file: str,
    location: str = None,
    date: str = None,
    config_path: str = "config/pipeline_config.json"
):
    """Test watermark on a single image"""
    
    input_path = Path(input_file)
    if not input_path.exists():
        logError(f"❌ Input file not found: {input_file}")
        return
    
    # Handle output path - if it's a directory or missing extension, create proper filename
    output_path = Path(output_file)
    if output_path.is_dir() or output_path.suffix == '':
        # If directory or no extension, create filename based on input
        if output_path.is_dir():
            output_dir = output_path
        else:
            output_dir = output_path.parent
            if output_path.name and output_path.name != '.':
                # Use the name as prefix if provided
                prefix = output_path.name
            else:
                prefix = input_path.stem + "_watermarked"
        
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Determine output format (default to webp)
        if output_path.suffix:
            ext = output_path.suffix
        else:
            ext = '.webp'
        
        # Create full output path
        if output_path.is_dir():
            output_file = str(output_dir / f"{input_path.stem}_watermarked{ext}")
        else:
            output_file = str(output_dir / f"{output_path.name}{ext}")
        
        logInfo(f"📂 Output will be: {output_file}")
    
    output_path = Path(output_file)
    
    # Load config
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    # Show what config we loaded
    font_cfg = config.get('watermark', {}).get('font', {})
    logInfo(f"📋 Loaded config from {config_path}")
    logInfo(f"   Font size: {font_cfg.get('size', 'NOT SET')}")
    logInfo(f"   Font family: {font_cfg.get('family', 'NOT SET')}")
    logInfo(f"   Margins: {config.get('watermark', {}).get('margin', 'NOT SET')}")
    
    # Enable watermarking in config
    if 'watermark' not in config:
        config['watermark'] = {}
    config['watermark']['enabled'] = True
    
    # If no location provided, try to extract from EXIF
    if location is None:
        logInfo("📍 Extracting location from EXIF...")
        geo_extractor = GeoExtractor(config)
        metadata = geo_extractor.extract_metadata(str(input_path))
        location = metadata.get('location_formatted', 'Unknown Location')
        logInfo(f"   Found: {location}")
        
        # Also get date from EXIF if not provided
        if date is None and metadata.get('date_taken'):
            date = metadata.get('date_taken')
            logInfo(f"   Date: {date}")
    
    # Parse date if provided
    photo_date = None
    if date:
        try:
            if isinstance(date, str):
                photo_date = datetime.fromisoformat(date.replace('Z', '+00:00'))
            else:
                photo_date = date
        except Exception as e:
            logError(f"⚠️  Could not parse date '{date}': {e}")
            photo_date = datetime.now()
    else:
        photo_date = datetime.now()
    
    # Generate watermark text
    watermark_gen = WatermarkGenerator(config)
    watermark_text = watermark_gen.generate_watermark(location, photo_date)
    
    logInfo(f"💧 Watermark text: {watermark_text}")
    
    # Show font configuration being used
    font_config = config.get('watermark', {}).get('font', {})
    logInfo(f"🔤 Font config: size={font_config.get('size', 'default')}, family={font_config.get('family', 'default')}")
    
    # Apply watermark
    watermark_app = WatermarkApplicator(config)
    
    try:
        watermark_app.apply_watermark(
            str(input_path),
            watermark_text,
            output_file
        )
        logInfo(f"✅ Watermarked image saved: {output_file}")
        
        # Show file sizes
        input_size = input_path.stat().st_size / 1024 / 1024  # MB
        output_size = Path(output_file).stat().st_size / 1024 / 1024  # MB
        logInfo(f"   Input: {input_size:.2f} MB")
        logInfo(f"   Output: {output_size:.2f} MB")
        
    except Exception as e:
        logError(f"❌ Watermarking failed: {e}")
        import traceback
        logError(traceback.format_exc())


def main():
    parser = argparse.ArgumentParser(
        description="Test watermarking on a single image",
        epilog="""
Examples:
  # Output to specific file (will auto-add .webp extension if missing)
  python test_watermark.py --file input.jpg --output test_output.webp
  
  # Output to directory (creates input_watermarked.webp)
  python test_watermark.py --file input.jpg --output /tmp/
  
  # Output with custom prefix (creates mytest.webp)
  python test_watermark.py --file input.jpg --output /tmp/mytest
  
  # Override location manually
  python test_watermark.py --file input.jpg --output test.webp --location "Tokyo, Japan"
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--file",
        required=True,
        help="Input image file"
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output path: file (e.g., output.webp), directory (e.g., /tmp/), or prefix (e.g., /tmp/test). Will auto-add .webp extension if missing."
    )
    parser.add_argument(
        "--location",
        help="Location text (e.g., 'Denver, CO'). If not provided, extracts from EXIF."
    )
    parser.add_argument(
        "--date",
        help="Photo date (ISO format: 2024-11-26T17:31:45). If not provided, uses current date or EXIF date."
    )
    parser.add_argument(
        "--config",
        default="config/pipeline_config.json",
        help="Pipeline config file"
    )
    
    args = parser.parse_args()
    
    test_watermark(
        input_file=args.file,
        output_file=args.output,
        location=args.location,
        date=args.date,
        config_path=args.config
    )


if __name__ == "__main__":
    main()
