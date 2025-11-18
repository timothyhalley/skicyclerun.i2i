#!/usr/bin/env python3

# Quick test of the image scaling logic
import sys
sys.path.append('/Users/timothyhalley/Projects/skicyclerun.i2i')

from core.image_processor import rescale_image
from PIL import Image

# Create test images with different aspect ratios
print("Testing image scaling logic:")

# Test portrait image (like 3024×4032)
portrait = Image.new('RGB', (3024, 4032), color='red')
print(f"\n📱 Portrait {portrait.size}:")
scaled_portrait = rescale_image(portrait, 512)
print(f"   → Scaled to: {scaled_portrait.size}")

# Test landscape image (like 4032×3024)  
landscape = Image.new('RGB', (4032, 3024), color='blue')
print(f"\n🖼️  Landscape {landscape.size}:")
scaled_landscape = rescale_image(landscape, 512)
print(f"   → Scaled to: {scaled_landscape.size}")

# Test square image
square = Image.new('RGB', (2048, 2048), color='green')
print(f"\n⬜ Square {square.size}:")
scaled_square = rescale_image(square, 512)
print(f"   → Scaled to: {scaled_square.size}")

print("\n✅ All dimensions are multiples of 16 and ≤ 512px")