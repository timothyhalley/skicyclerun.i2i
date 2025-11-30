"""
Post-LoRA Processing Script
Applies watermarks to LoRA-processed images (Phase 2.5)
This runs AFTER LoRA artistic processing to preserve watermark quality
"""
import json
import argparse
from pathlib import Path
from utils.time_utils import utc_now_iso_z
from core.watermark_generator import WatermarkGenerator
from core.watermark_applicator import WatermarkApplicator
from core.master_store import MasterStore
from utils.logger import logInfo, logWarn, logError


class PostLoRAProcessor:
    def __init__(self, config_path: str = "config/pipeline_config.json"):
        self.config = self._load_config(config_path)
        self.watermark_config = self.config.get('watermark', {})
        paths = self.config.get('paths', {})
        master_path = paths.get('master_catalog')
        self.master_store = MasterStore(master_path) if master_path else None
        # Derived path defaults from unified scaffold
        self.default_lora_input = paths.get('lora_processed')
        self.default_lora_watermarked = paths.get('final_albums')
        if not self.default_lora_watermarked and self.default_lora_input:
            self.default_lora_watermarked = str(Path(self.default_lora_input).parent / 'lora_final')
        
    def _load_config(self, config_path: str):
        """Load pipeline configuration"""
        with open(config_path, 'r') as f:
            return json.load(f)
    
    def find_metadata_for_image(self, lora_image_path: Path) -> dict:
        """
        Find suitable metadata for a LoRA-processed image using MasterStore.
        Prefer the corresponding preprocessed entry; fall back to raw entry by base name.
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
        
        if not self.master_store:
            logWarn(f"⚠️  MasterStore not available for metadata lookup")
            return {}
        
        # Try direct candidate path in preprocessed folder
        pre_dir_cfg = self.config.get('paths', {}).get('preprocessed')
        if pre_dir_cfg:
            pre_dir = Path(pre_dir_cfg)
            album_dir = lora_image_path.parent.name
            candidates = [
                pre_dir / album_dir / f"{original_base}.webp",
                pre_dir / album_dir / f"{original_base}.jpg",
                pre_dir / album_dir / f"{original_base}.jpeg",
                pre_dir / album_dir / f"{original_base}.png",
            ]
            for c in candidates:
                e = self.master_store.get(str(c))
                if e and 'preprocessing' in e.get('pipeline', {}).get('stages', []):
                    return {
                        'location_formatted': e.get('location_formatted'),
                        'date_taken_utc': (e.get('exif') or {}).get('date_taken_utc'),
                        'date_taken': (e.get('exif') or {}).get('date_taken'),
                        'landmarks': e.get('landmarks')
                    }
        
        # Fallback 1: Search raw entries by exact file_name match (without extension)
        base = original_base
        matches_found = 0
        for fp, e in self.master_store.list_paths().items():
            fp_path = Path(fp)
            if fp_path.stem == base:
                matches_found += 1
                if 'metadata_extraction' in e.get('pipeline', {}).get('stages', []):
                    logInfo(f"    ✓ Found metadata via stem match: {fp_path.name}")
                    return {
                        'location_formatted': e.get('location_formatted'),
                        'date_taken_utc': (e.get('exif') or {}).get('date_taken_utc'),
                        'date_taken': (e.get('exif') or {}).get('date_taken'),
                        'landmarks': e.get('landmarks')
                    }
        
        if matches_found > 0:
            logWarn(f"⚠️  Found {matches_found} stem matches for '{base}' but none had metadata_extraction stage")
        
        # Fallback 2: Try matching with original album folder structure
        # LoRA files are in: lora_processed/[Album]/imagename_style_timestamp.webp
        # Raw files might be in: albums/[Album]/imagename.jpeg
        album_name = lora_image_path.parent.name
        album_matches = 0
        for fp, e in self.master_store.list_paths().items():
            fp_path = Path(fp)
            # Check if album name is in path and stem matches
            if album_name in str(fp_path) and fp_path.stem == base:
                album_matches += 1
                logInfo(f"    ✓ Found metadata via album+stem match: {fp_path.name}")
                return {
                    'location_formatted': e.get('location_formatted'),
                    'date_taken_utc': (e.get('exif') or {}).get('date_taken_utc'),
                    'date_taken': (e.get('exif') or {}).get('date_taken'),
                    'landmarks': e.get('landmarks')
                }
        
        if album_matches > 0:
            logWarn(f"⚠️  Found {album_matches} album+stem matches for '{base}' in album '{album_name}' but couldn't extract metadata")
        
        logWarn(f"⚠️  No metadata found for {lora_image_path.name} (original_base: '{original_base}', album: '{album_name}')")
        logWarn(f"     Searched {len(self.master_store.list_paths())} entries in master store")
        return {}
    
    def watermark_lora_output(
        self, 
        lora_input_folder: str = None,
        output_folder: str = None,
        album_filter: str = None,
        style_filter: str = None,
        force: bool = False
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
        
        lora_input_folder = lora_input_folder or self.default_lora_input
        output_folder = output_folder or self.default_lora_watermarked
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
        
        # Log font configuration being used
        font_config = watermark_config.get('font', {})
        logInfo(f"🔤 Font config: size={font_config.get('size', 'NOT SET')}, family={font_config.get('family', 'NOT SET')}")
        
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
                
                # Skip if already watermarked (unless force=True)
                if output_file.exists() and not force:
                    skipped_count += 1
                    continue
                
                try:
                    # Find metadata for this image
                    metadata = self.find_metadata_for_image(image_file)
                    
                    # Debug: show what metadata was found
                    if metadata:
                        loc = metadata.get('location_formatted', 'NO LOCATION')
                        logInfo(f"    📍 Metadata found: {loc}")
                    else:
                        logWarn(f"    ⚠️  Empty metadata returned for {image_file.name}")
                    
                    # Try to infer LoRA style from filename
                    style_name = None
                    parts = image_file.stem.rsplit('_', 2)
                    if len(parts) == 3 and parts[-1].isdigit() and len(parts[-1]) == 8:
                        style_name = parts[1]
                    
                    # Generate watermark text
                    watermark_text = watermark_gen.generate_from_metadata(metadata)
                    
                    # Apply watermark
                    watermark_app.apply_watermark(
                        str(image_file),
                        watermark_text,
                        str(output_file)
                    )

                    # Update master store entry for the watermarked LoRA image
                    if self.master_store:
                        font_cfg = self.watermark_config.get('font', {})
                        wm_block = {
                            "text": watermark_text,
                            "font": {
                                "family": font_cfg.get("family"),
                                "size": font_cfg.get("size"),
                                "min_size": font_cfg.get("min_size"),
                                "max_width_percent": font_cfg.get("max_width_percent"),
                                "fit_mode": font_cfg.get("fit_mode"),
                            },
                            "position": self.watermark_config.get('position'),
                            "margin": self.watermark_config.get('margin'),
                            "applied_at": utc_now_iso_z(),
                            "input_path": str(image_file),
                            "output_path": str(output_file),
                        }
                        lora_block = {"style": style_name} if style_name else {}
                        patch = {
                            "type": "lora_watermarked",
                            "source_path": str(image_file),
                            "lora": lora_block,
                            "watermark": wm_block,
                        }
                        self.master_store.update_entry(str(output_file), patch, stage='post_lora_watermarking')
                    
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
        default=None,
        help="Folder with LoRA-processed images (default: from pipeline config)"
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output folder for watermarked images (default: from pipeline config)"
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
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-watermark existing images (overwrite)"
    )
    
    args = parser.parse_args()
    
    processor = PostLoRAProcessor(args.config)
    processor.watermark_lora_output(
        lora_input_folder=args.input or processor.default_lora_input,
        output_folder=args.output or processor.default_lora_watermarked,
        album_filter=args.album,
        style_filter=args.style,
        force=args.force
    )


if __name__ == "__main__":
    main()
