#!/usr/bin/env python3
"""Test aspect ratio preservation"""

import sys
sys.path.append('/Users/timothyhalley/Projects/skicyclerun.i2i')

from core.image_processor import load_and_prepare_image
from PIL import Image

print("Testing aspect ratio preservation:\n")

# Test with portrait image (768×1024 like your photo)
portrait = Image.new('RGB', (768, 1024), color='red')
portrait.save('/tmp/test_portrait.jpg')

result = load_and_prepare_image('/tmp/test_portrait.jpg', 1024, {'enabled': False})
print(f"Portrait 768×1024 → {result.size[0]}×{result.size[1]}")
print(f"  Aspect ratio: {result.size[0]/result.size[1]:.3f} (original: {768/1024:.3f})")

# Test with landscape  
landscape = Image.new('RGB', (1024, 768), color='blue')
landscape.save('/tmp/test_landscape.jpg')

result = load_and_prepare_image('/tmp/test_landscape.jpg', 1024, {'enabled': False})
print(f"\nLandscape 1024×768 → {result.size[0]}×{result.size[1]}")
print(f"  Aspect ratio: {result.size[0]/result.size[1]:.3f} (original: {1024/768:.3f})")

print("\n✅ Aspect ratios should be preserved and dimensions should be multiples of 16")
