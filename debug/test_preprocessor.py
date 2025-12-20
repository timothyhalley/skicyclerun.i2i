#!/usr/bin/env python3
"""
Test script for image preprocessor
Demonstrates preprocessing capabilities without running full pipeline
"""
import json, os
from core.image_preprocessor import ImagePreprocessor
from pathlib import Path
from utils.config_utils import resolve_config_placeholders

# Test configuration
config = {
    "preprocessing": {
        "enabled": True,
        "max_dimension": 2048,
        "format": "webp",
        "quality": 90,
        "preserve_aspect_ratio": True,
        "optimize": True
    }
}

# Test paths derived from pipeline config
with open("config/pipeline_config.json","r") as f:
    cfg = resolve_config_placeholders(json.load(f))
lib_root = cfg.get("paths",{}).get("lib_root") or os.getcwd()
input_dir = f"{lib_root}/raw"
output_dir = f"{lib_root}/scaled"
catalog_path = f"{lib_root}/metadata/preprocessing_catalog.json"

def main():
    print("🧪 Testing Image Preprocessor")
    print("=" * 60)
    
    preprocessor = ImagePreprocessor(config)
    
    # Check if input directory exists
    if not Path(input_dir).exists():
        print(f"❌ Input directory not found: {input_dir}")
        print("💡 Create it and add some test images first")
        return
    
    # Preprocess all images
    print(f"\n📂 Input: {input_dir}")
    print(f"📁 Output: {output_dir}")
    print(f"📋 Catalog: {catalog_path}\n")
    
    catalog = preprocessor.preprocess_directory(input_dir, output_dir)
    
    if catalog:
        # Save catalog
        preprocessor.save_catalog(catalog_path)
        
        # Show sample results
        print("\n📊 Sample Processing Results:")
        print("-" * 60)
        
        for i, (output_path, metadata) in enumerate(list(catalog.items())[:3], 1):
            print(f"\n{i}. {Path(output_path).name}")
            print(f"   Original: {metadata['original_size']['width']}×{metadata['original_size']['height']} ({metadata['original_file_size'] / 1024:.1f} KB)")
            print(f"   Processed: {metadata['processed_size']['width']}×{metadata['processed_size']['height']} ({metadata['processed_file_size'] / 1024:.1f} KB)")
            print(f"   Reduction: {metadata['size_reduction_percent']:.1f}%")
            print(f"   Format: {metadata['original_format']} → {metadata['output_format']}")
        
        if len(catalog) > 3:
            print(f"\n   ... and {len(catalog) - 3} more images")
        
        print("\n✅ Test complete!")
    else:
        print("\n⚠️  No images processed")

if __name__ == "__main__":
    main()
