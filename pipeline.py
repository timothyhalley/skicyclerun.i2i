"""
Pipeline Task Runner
Orchestrates the full photo processing pipeline from Apple Photos export to LoRA processing
"""
import json
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List
from core.geo_extractor import GeoExtractor
from core.watermark_generator import WatermarkGenerator
from core.watermark_applicator import WatermarkApplicator
from core.image_preprocessor import ImagePreprocessor
from utils.logger import logInfo, logError, logWarn


class PipelineRunner:
    def __init__(self, config_path: str = "config/pipeline_config.json"):
        self.config_path = config_path
        self.config = self._load_config()
        self.paths = self.config.get('paths', {})
        self.stages = self.config.get('pipeline', {}).get('stages', [])
        self.metadata_catalog = {}
        
    def _load_config(self) -> Dict:
        """Load pipeline configuration"""
        with open(self.config_path, 'r') as f:
            return json.load(f)
    
    def _save_metadata_catalog(self):
        """Save metadata catalog to JSON"""
        catalog_path = Path(self.paths.get('metadata_catalog', 'metadata/catalog.json'))
        catalog_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(catalog_path, 'w') as f:
            json.dump(self.metadata_catalog, f, indent=2)
        
        logInfo(f"💾 Saved metadata catalog: {catalog_path}")
    
    def run_export_stage(self):
        """Stage 1: Export photos from Apple Photos"""
        if not self.config.get('export', {}).get('enabled', False):
            logInfo("⏭️  Export stage disabled, skipping...")
            return
        
        logInfo("📸 Stage 1: Exporting from Apple Photos")
        
        script_path = self.config['export'].get('script_path', 'scripts/osxPhotoExporter.scpt')
        export_path = self.paths.get('apple_photos_export')
        
        try:
            result = subprocess.run(
                ['osascript', script_path, export_path],
                capture_output=True,
                text=True,
                timeout=3600  # 1 hour timeout
            )
            
            if result.returncode == 0:
                logInfo(f"✅ Export complete")
                logInfo(result.stdout)
            else:
                logError(f"❌ Export failed: {result.stderr}")
                
        except Exception as e:
            logError(f"❌ Export error: {e}")
    
    def run_cleanup_stage(self):
        """Stage 2: Cleanup old artifacts"""
        if not self.config.get('cleanup', {}).get('enabled', False):
            logInfo("⏭️  Cleanup stage disabled, skipping...")
            return
        
        logInfo("🧹 Stage 2: Cleaning up old artifacts")
        
        # Archive old outputs if configured
        if self.config['cleanup'].get('archive_old_outputs', False):
            output_path = Path(self.paths.get('output'))
            archive_path = Path(self.paths.get('archive'))
            
            if output_path.exists():
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                archive_dest = archive_path / f"archive_{timestamp}"
                archive_dest.mkdir(parents=True, exist_ok=True)
                
                # Move old outputs to archive
                for item in output_path.glob('*'):
                    if item.is_file():
                        item.rename(archive_dest / item.name)
                
                logInfo(f"📦 Archived old outputs to: {archive_dest}")
        
        logInfo("✅ Cleanup complete")
    
    def run_metadata_extraction_stage(self):
        """Stage 3: Extract metadata and geolocation"""
        if not self.config.get('metadata_extraction', {}).get('enabled', False):
            logInfo("⏭️  Metadata extraction disabled, skipping...")
            return
        
        logInfo("🗺️  Stage 3: Extracting metadata and geolocation")
        
        # Load existing catalog to check for duplicates
        catalog_path = Path(self.paths.get('metadata_catalog', 'metadata/catalog.json'))
        if catalog_path.exists():
            try:
                with open(catalog_path, 'r') as f:
                    self.metadata_catalog = json.load(f)
                logInfo(f"📖 Loaded existing catalog: {len(self.metadata_catalog)} entries")
            except Exception as e:
                logWarn(f"⚠️  Could not load existing catalog: {e}")
        
        geo_extractor = GeoExtractor(self.config)
        raw_input_path = Path(self.paths.get('raw_input'))
        
        # Process all images in input folder
        image_files = list(raw_input_path.glob('**/*.jpg')) + \
                     list(raw_input_path.glob('**/*.jpeg')) + \
                     list(raw_input_path.glob('**/*.png'))
        
        new_count = 0
        skipped_count = 0
        
        logInfo(f"📊 Found {len(image_files)} images in input folder...")
        
        for idx, image_path in enumerate(image_files, 1):
            image_path_str = str(image_path)
            
            # Skip if already in catalog (check for raw metadata without processed_size)
            if image_path_str in self.metadata_catalog and 'gps_coordinates' in self.metadata_catalog[image_path_str]:
                skipped_count += 1
                continue
            
            try:
                metadata = geo_extractor.extract_metadata(image_path_str)
                self.metadata_catalog[image_path_str] = metadata
                new_count += 1
                
                if new_count % 10 == 0:
                    logInfo(f"  Extracted metadata for {new_count} new images...")
                    
            except Exception as e:
                logWarn(f"⚠️  Failed to extract metadata from {image_path.name}: {e}")
        
        self._save_metadata_catalog()
        logInfo(f"✅ Metadata extraction complete - {new_count} new, {skipped_count} already cataloged")
    
    def run_preprocessing_stage(self):
        """Stage 4: Scale and optimize images"""
        if not self.config.get('preprocessing', {}).get('enabled', False):
            logInfo("⏭️  Preprocessing disabled, skipping...")
            return
        
        logInfo("🖼️  Stage 4: Preprocessing images")
        
        preprocessor = ImagePreprocessor(self.config)
        raw_input_path = self.paths.get('raw_input')
        preprocessed_path = self.paths.get('preprocessed')
        
        # Load existing metadata catalog if available
        catalog_path = Path(self.paths.get('metadata_catalog', 'metadata/catalog.json'))
        existing_catalog = {}
        if catalog_path.exists():
            try:
                with open(catalog_path, 'r') as f:
                    existing_catalog = json.load(f)
                logInfo(f"📖 Loaded existing metadata catalog: {len(existing_catalog)} entries")
            except Exception as e:
                logWarn(f"⚠️  Could not load existing catalog: {e}")
        
        # Preprocess all images
        processed_catalog = preprocessor.preprocess_directory(
            raw_input_path,
            preprocessed_path,
            existing_catalog
        )
        
        # Merge catalogs
        self.metadata_catalog.update(processed_catalog)
        self._save_metadata_catalog()
        
        logInfo("✅ Preprocessing complete")
    
    def run_watermarking_stage(self):
        """Stage 5: Apply watermarks"""
        if not self.config.get('watermark', {}).get('enabled', False):
            logInfo("⏭️  Watermarking disabled, skipping...")
            return
        
        logInfo("💧 Stage 5: Applying watermarks")
        
        # Load existing metadata catalog if not already loaded
        if not self.metadata_catalog:
            catalog_path = Path(self.paths.get('metadata_catalog', 'metadata/catalog.json'))
            if catalog_path.exists():
                try:
                    with open(catalog_path, 'r') as f:
                        self.metadata_catalog = json.load(f)
                    logInfo(f"📖 Loaded metadata catalog: {len(self.metadata_catalog)} entries")
                except Exception as e:
                    logWarn(f"⚠️  Could not load metadata catalog: {e}")
        
        if not self.metadata_catalog:
            logWarn("⚠️  No metadata catalog found. Run metadata_extraction and preprocessing stages first.")
            return
        
        from utils.filename_generator import FilenameGenerator
        watermark_gen = WatermarkGenerator(self.config)
        watermark_app = WatermarkApplicator(self.config)
        
        preprocessed_path = Path(self.paths.get('preprocessed'))
        output_path = Path(self.paths.get('output'))
        
        watermarked_count = 0
        
        # Process images from metadata catalog
        for image_path_str, metadata in self.metadata_catalog.items():
            try:
                # Check if this is a preprocessed image path
                image_path = Path(image_path_str)
                
                # Skip if not preprocessed (no processed_size field means it's from raw input)
                if 'processed_size' not in metadata:
                    continue
                
                if not image_path.exists():
                    logWarn(f"⚠️  Image not found: {image_path}")
                    continue
                
                # Extract album name from folder structure
                # Path structure: .../preprocessed/[album_name]/image.ext
                album_name = None
                try:
                    relative_to_preprocessed = image_path.relative_to(preprocessed_path)
                    if len(relative_to_preprocessed.parts) > 1:
                        album_name = relative_to_preprocessed.parts[0]
                except ValueError:
                    pass
                
                # Generate smart filename
                new_filename_stem = FilenameGenerator.generate_from_metadata(
                    metadata,
                    image_path.stem
                )
                
                # Determine output directory (preserve album structure)
                if album_name:
                    output_dir = output_path / album_name
                    output_dir.mkdir(parents=True, exist_ok=True)
                else:
                    output_dir = output_path
                
                # Ensure unique output path
                output_file = FilenameGenerator.ensure_unique_path(
                    output_dir,
                    new_filename_stem,
                    image_path.suffix
                )
                
                # Skip if output file already exists
                if output_file.exists():
                    watermarked_count += 1
                    continue
                
                # Generate watermark text
                watermark_text = watermark_gen.generate_from_metadata(metadata)
                
                # Apply watermark
                watermark_app.apply_watermark(
                    str(image_path),
                    watermark_text,
                    str(output_file)
                )
                
                watermarked_count += 1
                
                if watermarked_count % 10 == 0:
                    logInfo(f"  Watermarked {watermarked_count} images...")
                
            except Exception as e:
                logWarn(f"⚠️  Failed to watermark {image_path.name}: {e}")
        
        logInfo(f"✅ Watermarking complete - {watermarked_count} images processed")
    
    def run_lora_processing_stage(self):
        """Stage 6: Apply LoRA style filters"""
        if not self.config.get('lora_processing', {}).get('enabled', False):
            logInfo("⏭️  LoRA processing disabled, skipping...")
            return
        
        logInfo("🎨 Stage 6: Applying LoRA style filters")
        
        # This integrates with existing main.py
        # For now, log that it should be run separately
        logInfo("💡 Run main.py with --batch to process images through LoRA pipeline")
        logInfo("   Example: python main.py --lora American_Cartoon --batch")
    
    def run_pipeline(self, stages: List[str] = None):
        """Run the full pipeline or specific stages"""
        if stages is None:
            stages = self.stages
        
        logInfo(f"🚀 Starting SkiCycleRun Pipeline")
        logInfo(f"📋 Stages to run: {', '.join(stages)}")
        
        stage_map = {
            'export': self.run_export_stage,
            'cleanup': self.run_cleanup_stage,
            'metadata_extraction': self.run_metadata_extraction_stage,
            'preprocessing': self.run_preprocessing_stage,
            'watermarking': self.run_watermarking_stage,
            'lora_processing': self.run_lora_processing_stage
        }
        
        for stage in stages:
            if stage in stage_map:
                stage_map[stage]()
            else:
                logWarn(f"⚠️  Unknown stage: {stage}")
        
        logInfo("🎉 Pipeline complete!")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="SkiCycleRun Photo Processing Pipeline")
    parser.add_argument("--config", default="config/pipeline_config.json", help="Pipeline config file")
    parser.add_argument("--stages", nargs='+', help="Specific stages to run")
    
    args = parser.parse_args()
    
    runner = PipelineRunner(args.config)
    runner.run_pipeline(args.stages)
