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
        watermarked_path = Path(self.paths.get('watermarked', self.paths.get('output')))
        
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
                    output_dir = watermarked_path / album_name
                    output_dir.mkdir(parents=True, exist_ok=True)
                else:
                    output_dir = watermarked_path
                
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
        
        lora_config = self.config.get('lora_processing', {})
        loras_to_process = lora_config.get('loras_to_process', [])
        
        if not loras_to_process:
            logWarn("⚠️  No LoRAs specified in config. Add 'loras_to_process' array to lora_processing config.")
            return
        
        input_folder = lora_config.get('input_folder', self.paths.get('preprocessed'))
        output_folder = lora_config.get('output_folder', '/Volumes/MySSD/ImageLib/phase2_lora/processed')
        
        logInfo(f"📁 Input: {input_folder}")
        logInfo(f"📂 Output: {output_folder}")
        logInfo(f"🎨 Processing {len(loras_to_process)} LoRA styles: {', '.join(loras_to_process)}")
        
        # Import main.py functions
        import sys
        import subprocess
        
        for lora_name in loras_to_process:
            logInfo("=" * 80)
            logInfo(f"🎨 STARTING LoRA PROCESSING: {lora_name}")
            logInfo(f"📂 Input folder: {input_folder}")
            logInfo(f"📂 Output folder: {output_folder}")
            logInfo("=" * 80)
            
            # Call main.py with batch processing
            cmd = [
                sys.executable, 
                'main.py',
                '--lora', lora_name,
                '--batch',
                '--input-folder', input_folder,
                '--output-folder', output_folder
            ]
            
            try:
                # Don't capture output - let it stream to console for spinners and progress
                result = subprocess.run(cmd, check=True)
                logInfo(f"\n✅ {lora_name} processing complete")
            except subprocess.CalledProcessError as e:
                logError(f"\n❌ {lora_name} processing failed: {e}")
                # Continue with next LoRA instead of stopping
        
        logInfo(f"✅ LoRA processing complete - {len(loras_to_process)} styles processed")
    
    def run_post_lora_watermarking_stage(self):
        """Stage 7: Apply watermarks to LoRA-processed images"""
        logInfo("💧 Stage 7: Watermarking LoRA-processed images")
        
        lora_config = self.config.get('lora_processing', {})
        lora_output = lora_config.get('output_folder', '/Volumes/MySSD/ImageLib/phase2_lora/processed')
        watermark_output = '/Volumes/MySSD/ImageLib/phase2_lora/watermarked'
        
        logInfo(f"📁 Input: {lora_output}")
        logInfo(f"📂 Output: {watermark_output}")
        
        # Call postprocess_lora.py
        import sys
        import subprocess
        
        cmd = [
            sys.executable,
            'postprocess_lora.py',
            '--input', lora_output,
            '--output', watermark_output
        ]
        
        try:
            # Don't capture output - let it stream to console for progress feedback
            result = subprocess.run(cmd, check=True)
            logInfo("\n✅ Post-LoRA watermarking complete")
        except subprocess.CalledProcessError as e:
            logError(f"\n❌ Post-LoRA watermarking failed: {e}")
    
    def run_s3_deployment_stage(self):
        """Stage 8: Deploy watermarked images to AWS S3"""
        if not self.config.get('s3_deployment', {}).get('enabled', False):
            logInfo("⏭️  S3 deployment disabled, skipping...")
            return
        
        logInfo("☁️  Stage 8: Deploying to AWS S3")
        
        s3_config = self.config.get('s3_deployment', {})
        source_folder = Path(s3_config.get('source_folder', '/Volumes/MySSD/ImageLib/phase2_lora/watermarked'))
        bucket_name = s3_config.get('bucket_name', 'skicyclerun.lib')
        bucket_prefix = s3_config.get('bucket_prefix', 'albums')
        aws_profile = s3_config.get('aws_profile', 'default')
        dry_run = s3_config.get('dry_run', False)
        
        if not source_folder.exists():
            logError(f"❌ Source folder not found: {source_folder}")
            return
        
        logInfo(f"📁 Source: {source_folder}")
        logInfo(f"☁️  Bucket: s3://{bucket_name}/{bucket_prefix}/")
        logInfo(f"🔑 AWS Profile: {aws_profile}")
        
        if dry_run:
            logInfo("🏃 DRY RUN MODE - No files will be uploaded")
        
        try:
            import boto3
            from botocore.exceptions import ClientError, NoCredentialsError
            
            # Initialize S3 client with profile
            session = boto3.Session(profile_name=aws_profile)
            s3_client = session.client('s3')
            
            # Verify bucket access
            try:
                s3_client.head_bucket(Bucket=bucket_name)
                logInfo(f"✅ Bucket '{bucket_name}' is accessible")
            except ClientError as e:
                error_code = e.response['Error']['Code']
                if error_code == '404':
                    logError(f"❌ Bucket '{bucket_name}' does not exist")
                elif error_code == '403':
                    logError(f"❌ Access denied to bucket '{bucket_name}'")
                else:
                    logError(f"❌ Bucket access error: {e}")
                return
            
            # Upload files
            total_files = 0
            uploaded_files = 0
            skipped_files = 0
            
            # Walk through album/style folders
            for album_dir in source_folder.iterdir():
                if not album_dir.is_dir():
                    continue
                
                album_name = album_dir.name
                logInfo(f"\n📂 Processing album: {album_name}")
                
                # Find all image files in album (across all style folders if they exist)
                image_files = []
                if any(album_dir.iterdir()):
                    # Check if album has style subfolders or direct images
                    has_subfolders = any(p.is_dir() for p in album_dir.iterdir())
                    
                    if has_subfolders:
                        # Album/Style/Images structure
                        for style_dir in album_dir.iterdir():
                            if style_dir.is_dir():
                                for ext in ['.webp', '.jpg', '.jpeg', '.png']:
                                    image_files.extend(style_dir.glob(f'*{ext}'))
                    else:
                        # Album/Images structure (no style subfolders)
                        for ext in ['.webp', '.jpg', '.jpeg', '.png']:
                            image_files.extend(album_dir.glob(f'*{ext}'))
                
                for image_file in image_files:
                    total_files += 1
                    
                    # Construct S3 key: albums/[album_name]/[filename]
                    s3_key = f"{bucket_prefix}/{album_name}/{image_file.name}"
                    
                    if dry_run:
                        logInfo(f"  [DRY RUN] Would upload: {image_file.name} → s3://{bucket_name}/{s3_key}")
                        uploaded_files += 1
                        continue
                    
                    try:
                        # Check if file already exists in S3
                        try:
                            s3_client.head_object(Bucket=bucket_name, Key=s3_key)
                            skipped_files += 1
                            continue
                        except ClientError:
                            pass  # File doesn't exist, proceed with upload
                        
                        # Upload file
                        extra_args = {
                            'ContentType': s3_config.get('content_type', 'image/webp'),
                            'CacheControl': s3_config.get('cache_control', 'max-age=31536000, public'),
                        }
                        
                        if s3_config.get('acl'):
                            extra_args['ACL'] = s3_config.get('acl')
                        
                        if s3_config.get('storage_class'):
                            extra_args['StorageClass'] = s3_config.get('storage_class')
                        
                        s3_client.upload_file(
                            str(image_file),
                            bucket_name,
                            s3_key,
                            ExtraArgs=extra_args
                        )
                        
                        uploaded_files += 1
                        
                        if uploaded_files % 10 == 0:
                            logInfo(f"  Uploaded {uploaded_files}/{total_files} files...")
                        
                    except ClientError as e:
                        logError(f"  ❌ Failed to upload {image_file.name}: {e}")
            
            logInfo(f"\n✅ S3 deployment complete")
            logInfo(f"📊 Total: {total_files} files | Uploaded: {uploaded_files} | Skipped: {skipped_files}")
            logInfo(f"🌐 View at: https://{bucket_name}.s3.amazonaws.com/{bucket_prefix}/")
            
        except ImportError:
            logError("❌ boto3 not installed. Install with: pip install boto3")
        except NoCredentialsError:
            logError(f"❌ AWS credentials not found for profile '{aws_profile}'")
            logError("   Configure credentials with: aws configure --profile {aws_profile}")
        except Exception as e:
            logError(f"❌ S3 deployment failed: {e}")
            import traceback
            logError(traceback.format_exc())
    
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
            'lora_processing': self.run_lora_processing_stage,
            'post_lora_watermarking': self.run_post_lora_watermarking_stage,
            's3_deployment': self.run_s3_deployment_stage
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
