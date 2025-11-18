#!/usr/bin/env python3
"""Debug font loading and rendering"""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

# Test font paths
font_paths = [
    "/System/Library/Fonts/Courier New Bold.ttf",
    "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
    "/System/Library/Fonts/Supplemental/Courier New.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf"
]

print("Testing font paths:")
for fp in font_paths:
    exists = Path(fp).exists()
    print(f"  {'✓' if exists else '✗'} {fp}")

# Find first available font
font_path = None
for fp in font_paths:
    if Path(fp).exists():
        font_path = fp
        break

if font_path:
    print(f"\n✅ Using font: {font_path}")
    
    # Test different sizes
    test_sizes = [24, 32, 49, 64, 96]
    test_text = "SkiCycleRun © 2026 ▲ Denver, CO"
    
    print(f"\nCreating test image with sizes: {test_sizes}")
    
    # Create a test image
    img = Image.new('RGB', (1200, 800), color='white')
    draw = ImageDraw.Draw(img)
    
    y_pos = 50
    for size in test_sizes:
        try:
            font = ImageFont.truetype(font_path, size)
            bbox = draw.textbbox((0, 0), test_text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            
            # Draw size label
            label_font = ImageFont.truetype(font_path, 16)
            draw.text((10, y_pos), f"Size {size}px (width: {text_width}px):", 
                     font=label_font, fill='blue')
            
            # Draw actual text
            draw.text((10, y_pos + 25), test_text, font=font, fill='black',
                     stroke_width=2, stroke_fill='gray')
            
            y_pos += 100
            print(f"  Size {size}: {text_width}px × {text_height}px")
            
        except Exception as e:
            print(f"  Size {size}: ERROR - {e}")
    
    output_path = "font_size_test.png"
    img.save(output_path)
    print(f"\n✅ Saved to: {output_path}")
    print(f"   Open this file to compare sizes visually")
    
else:
    print("\n❌ No fonts available!")
