#!/usr/bin/env python3
"""
Comprehensive watermark diagnostic
Tests both test_watermark.py path and postprocess_lora.py path
"""
import json, os
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.watermark_generator import WatermarkGenerator
from core.watermark_applicator import WatermarkApplicator
from PIL import Image

# Load config
config_path = Path("config/pipeline_config.json")
from utils.config_utils import resolve_config_placeholders
with open(config_path) as f:
    config = resolve_config_placeholders(json.load(f))

print("=" * 80)
print("WATERMARK CONFIGURATION DIAGNOSTIC")
print("=" * 80)

# Check config
wm_config = config.get('watermark', {})
font_config = wm_config.get('font', {})

print(f"\n1. CONFIG FILE: {config_path.absolute()}")
print(f"   Font size: {font_config.get('size')}")
print(f"   Font family: {font_config.get('family')}")
print(f"   Color: {font_config.get('color')}")
print(f"   Stroke width: {font_config.get('stroke_width')}")
print(f"   Margin: {wm_config.get('margin')}")
print(f"   Position: {wm_config.get('position')}")

# Test watermark generator
print(f"\n2. WATERMARK GENERATOR TEST")
wm_gen = WatermarkGenerator(config)
test_text = wm_gen.generate_watermark("Denver, CO")
print(f"   Generated text: {test_text}")
print(f"   Symbol: {wm_gen.get_brand_symbol()}")

# Test watermark applicator initialization
print(f"\n3. WATERMARK APPLICATOR TEST")
wm_app = WatermarkApplicator(config)
print(f"   Config loaded: {wm_app.watermark_config is not None}")
print(f"   Font config: {wm_app.font_config}")
print(f"   Position: {wm_app.position}")
print(f"   Margin: {wm_app.margin}")

# Test font loading with different image widths
print(f"\n4. FONT LOADING TEST (different image widths)")
for width in [1024, 2048, 4096]:
    font = wm_app._get_font(width)
    print(f"   Image width {width}px:")
    print(f"     Font object: {font}")
    print(f"     Font size from config: {wm_app.font_config.get('size', 'NOT SET')}")
    
    # Try to get actual font size (if truetype)
    try:
        if hasattr(font, 'size'):
            print(f"     Actual font.size: {font.size}")
    except:
        pass

# Test with actual image dimensions
print(f"\n5. ACTUAL RENDERING TEST")
paths_config = config.get('paths', {})
lib_root = paths_config.get('lib_root') or os.getcwd()
preprocessed_dir = paths_config.get('preprocessed', f"{lib_root}/scaled")
test_image = f"{preprocessed_dir}/test/IMG_4394.jpeg"
if Path(test_image).exists():
    img = Image.open(test_image)
    print(f"   Test image: {test_image}")
    print(f"   Dimensions: {img.width}x{img.height}")
    
    font = wm_app._get_font(img.width)
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), test_text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    
    print(f"   Text dimensions: {text_width}x{text_height}")
    print(f"   Text width ratio: {text_width/img.width*100:.1f}% of image width")
else:
    print(f"   Test image not found: {test_image}")

# Check for any other config files
print(f"\n6. CHECKING FOR OTHER CONFIG FILES")
for cfg_file in Path("config").glob("*.json"):
    if 'watermark' in cfg_file.read_text():
        print(f"   Found: {cfg_file}")

print("\n" + "=" * 80)
print("DIAGNOSTIC COMPLETE")
print("=" * 80)
