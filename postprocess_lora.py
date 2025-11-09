"""
Post-LoRA Processing Script
Applies watermarks to LoRA-processed images (Phase 2.5)
This runs AFTER LoRA artistic processing to preserve watermark quality
"""
import json
import argparse
from pathlib import Path
from core.watermark_generator import WatermarkGenerator
from core.watermark_applicator import WatermarkApplicator
from utils.logger import logInfo, logWarn, logError


class PostLoRAProcessor:
    def __init__(self, config_path: str = "config/pipeline_config.json"):
        self.config = self._load_config(config_path)
        self.watermark_config = self.config.get('watermark', {})
        self.metadata_catalog = self._load_metadata_catalog()
        
    def _load_config(self, config_path: str):
        """Load pipeline configuration"""
        with open(config_path, 'r') as f:
            return json.load(f)
    
    def _load_metadata_catalog(self):
        """Load metadata catalog from Phase 1"""
        catalog_path = Path(self.config.get('paths', {}).get(
            'metadata_catalog', 
            '/Volumes/MySSD/ImageLib/phase1_extract/metadata/catalog.json'
        ))
        
        if not catalog_path.exists():
            logWarn(f"⚠️  Metadata catalog not found: {catalog_path}")
            return {}
        
        try:
            with open(catalog_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            logError(f"Failed to load metadata catalog: {e}")
            return {}
    
    def find_metadata_for_image(self, lora_image_path: Path) -> dict:
        """
        Find original metadata for a LoRA-processed image
        Matches by filename across the catalog
        
        LoRA files are named: {base_name}_{style}_{timestamp}.webp
        We need to strip the style and timestamp to match the original
        """
        filename_base = lora_image_path.stem
        
        # Strip LoRA suffix pattern: _{style}_{timestamp}
        # Example: "montreal_quebec_143045_GorillazStyle_08143521" -> "montreal_quebec_143045"
        parts = filename_base.rsplit('_', 2)  # Split from right, max 2 splits
        if len(parts) == 3:
            # Check if last part looks like timestamp (8 digits)
            if parts[-1].isdigit() and len(parts[-1]) == 8:
                # Second-to-last part should be the style name
                original_base = parts[0]
            else:
                original_base = filename_base
        else:
            original_base = filename_base
        
        # Try to find matching entry in catalog
        # The catalog has paths from scaled folder, we need to match by filename
        for catalog_path, metadata in self.metadata_catalog.items():
            catalog_filename = Path(catalog_path).stem
            
            # Match by base filename (exact or contained)
            if catalog_filename == original_base or \
               catalog_filename in original_base or \
               original_base in catalog_filename:
                return metadata
        
        # If not found, return empty metadata
        logWarn(f"⚠️  No metadata found for {lora_image_path.name} (base: {original_base})")
        return {}
    
    def watermark_lora_output(
        self, 
        lora_input_folder: str = "/Volumes/MySSD/ImageLib/phase2_lora/processed",
        output_folder: str = "/Volumes/MySSD/ImageLib/phase2_lora/watermarked",
        album_filter: str = None,
        style_filter: str = None
    ):
        """
        Apply watermarks to all LoRA-processed images
        
        Args:
            lora_input_folder: Folder with LoRA-processed images
            output_folder: Folder for watermarked output
            album_filter: Optional - only process specific album
            style_filter: Optional - only process specific style
        """
        logInfo("💧 Phase 2.5: Watermarking LoRA-processed images")
        
        lora_path = Path(lora_input_folder)
        output_path = Path(output_folder)
        
        if not lora_path.exists():
            logError(f"LoRA input folder not found: {lora_input_folder}")
            return
        
        # Enable watermarking temporarily
        watermark_config = self.watermark_config.copy()
        watermark_config['enabled'] = True
        temp_config = self.config.copy()
        temp_config['watermark'] = watermark_config
        
        watermark_gen = WatermarkGenerator(temp_config)
        watermark_app = WatermarkApplicator(temp_config)
        
        # Find all LoRA-processed images
        # Structure: lora_input/[Album]/image_{style}_{timestamp}.webp (flat structure)
        total_count = 0
        watermarked_count = 0
        skipped_count = 0
        
        for album_dir in lora_path.iterdir():
            if not album_dir.is_dir():
                continue
            
            # Apply album filter
            if album_filter and album_dir.name != album_filter:
                continue
            
            logInfo(f"📁 Processing album: {album_dir.name}")
            
            # Process all images directly in album folder (flat structure)
            image_files = list(album_dir.glob('*.webp')) + \
                         list(album_dir.glob('*.jpg')) + \
                         list(album_dir.glob('*.jpeg')) + \
                         list(album_dir.glob('*.png'))
            
            for image_file in image_files:
                # Apply style filter if specified (check filename contains style)
                if style_filter and f"_{style_filter}_" not in image_file.name:
                    continue
                
                total_count += 1
                
                # Create output path maintaining album structure
                output_album_dir = output_path / album_dir.name
                output_album_dir.mkdir(parents=True, exist_ok=True)
                output_file = output_album_dir / image_file.name
                
                # Skip if already watermarked
                if output_file.exists():
                    skipped_count += 1
                    continue
                
                try:
                    # Find metadata for this image
                    metadata = self.find_metadata_for_image(image_file)
                    
                    # Generate watermark text
                    watermark_text = watermark_gen.generate_from_metadata(metadata)
                    
                    # Apply watermark
                    watermark_app.apply_watermark(
                        str(image_file),
                        watermark_text,
                        str(output_file)
                    )
                    
                    watermarked_count += 1
                    
                    if watermarked_count % 10 == 0:
                        logInfo(f"    Watermarked {watermarked_count} images...")
                    
                except Exception as e:
                    logWarn(f"⚠️  Failed to watermark {image_file.name}: {e}")
        
        logInfo(f"✅ Watermarking complete!")
        logInfo(f"   Total: {total_count} images")
        logInfo(f"   Watermarked: {watermarked_count}")
        logInfo(f"   Skipped: {skipped_count} (already done)")
        logInfo(f"   Output: {output_folder}")


def main():
    parser = argparse.ArgumentParser(
        description="Apply watermarks to LoRA-processed images (Phase 2.5)"
    )
    parser.add_argument(
        "--input",
        default="/Volumes/MySSD/ImageLib/phase2_lora/processed",
        help="Folder with LoRA-processed images"
    )
    parser.add_argument(
        "--output",
        default="/Volumes/MySSD/ImageLib/phase2_lora/watermarked",
        help="Output folder for watermarked images"
    )
    parser.add_argument(
        "--album",
        help="Only process specific album"
    )
    parser.add_argument(
        "--style",
        help="Only process specific LoRA style"
    )
    parser.add_argument(
        "--config",
        default="config/pipeline_config.json",
        help="Pipeline config file"
    )
    
    args = parser.parse_args()
    
    processor = PostLoRAProcessor(args.config)
    processor.watermark_lora_output(
        lora_input_folder=args.input,
        output_folder=args.output,
        album_filter=args.album,
        style_filter=args.style
    )


if __name__ == "__main__":
    main()
