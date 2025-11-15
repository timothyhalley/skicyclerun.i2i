"""
Pipeline Task Runner
Orchestrates the full photo processing pipeline from Apple Photos export to LoRA processing
"""
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime
from utils.time_utils import utc_now_iso_z
from typing import Dict, List
from core.geo_extractor import GeoExtractor
from core.watermark_generator import WatermarkGenerator
from core.watermark_applicator import WatermarkApplicator
from core.image_preprocessor import ImagePreprocessor
from core.master_store import MasterStore
from utils.logger import logInfo, logError, logWarn


class PipelineRunner:
    def __init__(
        self,
        config_path: str = "config/pipeline_config.json",
        cache_only_geocode: bool | None = None,
        sweep_path_contains: str | None = None,
        sweep_limit: int | None = None,
        sweep_only_missing: bool = False,
        sweep_skip_poi: bool = False,
        sweep_skip_heading: bool = False,
        sweep_pulse_sec: int = 5,
    ):
        self.config_path = config_path
        self.config = self._load_config()
        self.paths = self.config.get('paths', {})
        self.stages = self.config.get('pipeline', {}).get('stages', [])
        self.metadata_catalog = {}
        master_path = self.paths.get('master_catalog')
        self.master_store: MasterStore | None = MasterStore(master_path) if master_path else None
        # Optional override for geocoding cache-only mode
        if cache_only_geocode is not None:
            self.config.setdefault('metadata_extraction', {}).setdefault('geocoding', {})['cache_only'] = bool(cache_only_geocode)
        # Sweep filters
        self.sweep_path_contains = sweep_path_contains
        self.sweep_limit = sweep_limit
        self.sweep_only_missing = sweep_only_missing
        self.sweep_skip_poi = sweep_skip_poi
        self.sweep_skip_heading = sweep_skip_heading
        self.sweep_pulse_sec = max(1, int(sweep_pulse_sec))
        
    def _load_config(self) -> Dict:
        """Load pipeline configuration"""
        with open(self.config_path, 'r') as f:
            return json.load(f)
    
    # Legacy catalog removed; MasterStore is authoritative.

    # Master catalog rebuild removed; using incremental MasterStore updates instead.
    
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
        
        # Legacy catalog retired; skipping reads.
        
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
            
            # Skip if master_store already recorded metadata_extraction for this raw path
            if self.master_store and self.master_store.has_stage(image_path_str, 'metadata_extraction'):
                skipped_count += 1
                continue
            
            try:
                metadata = geo_extractor.extract_metadata(image_path_str)
                # In-memory legacy tracking removed; write only to master
                # Write directly to master_store
                if self.master_store:
                    patch = {
                        "exif": {
                            "date_taken": metadata.get("date_taken"),
                            "date_taken_utc": metadata.get("date_taken_utc"),
                        },
                        "gps": metadata.get("gps_coordinates"),
                        "location": metadata.get("location"),
                        "location_formatted": metadata.get("location_formatted"),
                        "landmarks": metadata.get("landmarks"),
                        "heading": metadata.get("heading"),
                        "extracted_timestamp": metadata.get("timestamp"),
                    }
                    self.master_store.update_entry(image_path_str, patch, stage='metadata_extraction')
                new_count += 1
                
                if new_count % 10 == 0:
                    logInfo(f"  Extracted metadata for {new_count} new images...")
                    
            except Exception as e:
                logWarn(f"⚠️  Failed to extract metadata from {image_path.name}: {e}")
        
        logInfo(f"✅ Metadata extraction complete - {new_count} new, {skipped_count} skipped (existing)")
        # No rebuild: master_store already incrementally updated

    # Master catalog stage removed; no longer needed with MasterStore.
    
    def run_preprocessing_stage(self):
        """Stage 4: Scale and optimize images"""
        if not self.config.get('preprocessing', {}).get('enabled', False):
            logInfo("⏭️  Preprocessing disabled, skipping...")
            return
        
        logInfo("🖼️  Stage 4: Preprocessing images")
        
        preprocessor = ImagePreprocessor(self.config)
        raw_input_path = self.paths.get('raw_input')
        preprocessed_path = self.paths.get('preprocessed')
        
        # Build a combined existing catalog from MasterStore for skipping and metadata merge
        existing_catalog = {}
        if self.master_store:
            for fp, entry in self.master_store.list_paths().items():
                # preprocessed entries for skip
                if entry.get("preprocessing") and entry.get("type") == "preprocessed":
                    # mimic preprocessor expected shape, include sizes if available
                    pre = entry.get("preprocessing", {})
                    existing_catalog[fp] = {
                        'processed_size': pre.get('processed_size'),
                        'output_path': pre.get('output_path'),
                        'input_path': pre.get('input_path'),
                        'original_file_size': pre.get('original_file_size'),
                        'processed_file_size': pre.get('processed_file_size'),
                        'original_format': pre.get('original_format'),
                        'output_format': pre.get('output_format'),
                        'quality': pre.get('quality'),
                    }
                # raw metadata to merge into processing output
                if 'metadata_extraction' in entry.get('pipeline', {}).get('stages', []):
                    # Provide date/location fields under raw path key
                    raw_path = fp
                    existing_catalog[raw_path] = {
                        'date_taken': entry.get('exif', {}).get('date_taken'),
                        'date_taken_utc': entry.get('exif', {}).get('date_taken_utc'),
                        'location_formatted': entry.get('location_formatted'),
                        'location': entry.get('location'),
                    }
        
        # Preprocess all images
        processed_catalog = preprocessor.preprocess_directory(
            raw_input_path,
            preprocessed_path,
            existing_catalog
        )
        
        # No legacy catalog writes

        # Update master store entries per processed output
        if self.master_store:
            for out_path, meta in processed_catalog.items():
                section = {
                    "input_path": meta.get("input_path"),
                    "output_path": meta.get("output_path"),
                    "original_size": meta.get("original_size"),
                    "processed_size": meta.get("processed_size"),
                    "original_format": meta.get("original_format"),
                    "output_format": meta.get("output_format"),
                    "original_file_size": meta.get("original_file_size"),
                    "processed_file_size": meta.get("processed_file_size"),
                    "size_reduction_percent": meta.get("size_reduction_percent"),
                    "processed_timestamp": meta.get("processed_timestamp"),
                    "quality": meta.get("quality"),
                }
                patch = {
                    "type": "preprocessed",
                    "source_path": meta.get("input_path"),
                    "preprocessing": section,
                }
                # Carry through helpful top-level fields if present
                if meta.get('location_formatted'):
                    patch['location_formatted'] = meta.get('location_formatted')
                if meta.get('date_taken'):
                    patch.setdefault('exif', {})['date_taken'] = meta.get('date_taken')
                if meta.get('date_taken_utc'):
                    patch.setdefault('exif', {})['date_taken_utc'] = meta.get('date_taken_utc')
                self.master_store.update_entry(out_path, patch, stage='preprocessing')
        
        logInfo("✅ Preprocessing complete")
    
    def run_watermarking_stage(self):
        """Stage 5: Apply watermarks"""
        if not self.config.get('watermark', {}).get('enabled', False):
            logInfo("⏭️  Watermarking disabled, skipping...")
            return
        
        logInfo("💧 Stage 5: Applying watermarks")
        
        # Build list of preprocessed images directly from filesystem
        if not self.master_store:
            logWarn("⚠️  MasterStore not configured; cannot run watermarking stage reliably.")
            return
        
        from utils.filename_generator import FilenameGenerator
        watermark_gen = WatermarkGenerator(self.config)
        watermark_app = WatermarkApplicator(self.config)
        
        preprocessed_path = Path(self.paths.get('preprocessed'))
        watermarked_path = Path(self.paths.get('watermarked', self.paths.get('output')))
        
        watermarked_count = 0
        
        # Discover preprocessed images and watermark using MasterStore metadata
        image_files = list(preprocessed_path.glob('**/*.webp')) + \
                      list(preprocessed_path.glob('**/*.jpg')) + \
                      list(preprocessed_path.glob('**/*.jpeg')) + \
                      list(preprocessed_path.glob('**/*.png'))
        for image_path in image_files:
            try:
                image_path_str = str(image_path)
                
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
                # Fetch metadata from master store; fallback to source entry if needed
                entry = self.master_store.get(image_path_str)
                src_entry = None
                if entry and not entry.get('location_formatted') and entry.get('source_path'):
                    src_entry = self.master_store.get(entry.get('source_path'))
                e = entry or {}
                s = src_entry or {}
                meta_for_wm = {
                    'location_formatted': e.get('location_formatted') or s.get('location_formatted'),
                    'date_taken_utc': (e.get('exif') or {}).get('date_taken_utc') or (s.get('exif') or {}).get('date_taken_utc'),
                    'date_taken': (e.get('exif') or {}).get('date_taken') or (s.get('exif') or {}).get('date_taken'),
                    'landmarks': e.get('landmarks') or s.get('landmarks')
                }
                new_filename_stem = FilenameGenerator.generate_from_metadata(meta_for_wm, image_path.stem)
                
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
                
                # Skip if output file already exists or recorded in master
                if output_file.exists() or (self.master_store and self.master_store.has_stage(str(output_file), 'watermarking')):
                    watermarked_count += 1
                    continue
                
                # Generate watermark text
                watermark_text = watermark_gen.generate_from_metadata(meta_for_wm)
                
                # Apply watermark
                watermark_app.apply_watermark(
                    str(image_path),
                    watermark_text,
                    str(output_file)
                )

                # Record in master store
                if self.master_store:
                    font_cfg = self.config.get('watermark', {}).get('font', {})
                    wm_block = {
                        "text": watermark_text,
                        "font": {
                            "family": font_cfg.get("family"),
                            "size": font_cfg.get("size"),
                            "min_size": font_cfg.get("min_size"),
                            "max_width_percent": font_cfg.get("max_width_percent"),
                            "fit_mode": font_cfg.get("fit_mode"),
                        },
                        "position": self.config.get('watermark', {}).get('position'),
                        "margin": self.config.get('watermark', {}).get('margin'),
                        "applied_at": utc_now_iso_z(),
                        "input_path": str(image_path),
                        "output_path": str(output_file),
                    }
                    patch = {
                        "type": "watermarked",
                        "source_path": str(image_path),
                        "watermark": wm_block,
                    }
                    self.master_store.update_entry(str(output_file), patch, stage='watermarking')
                
                watermarked_count += 1
                
                if watermarked_count % 10 == 0:
                    logInfo(f"  Watermarked {watermarked_count} images...")
                
            except Exception as e:
                logWarn(f"⚠️  Failed to watermark {image_path.name}: {e}")
        
        logInfo(f"✅ Watermarking complete - {watermarked_count} images processed")

    def run_geocode_sweep_stage(self):
        """Stage: Sweep master.json and fill missing locations for entries with GPS.

        Forces network geocoding (ignores cache_only) and propagates location
        to derived entries that reference a source via source_path.
        Also enriches EXIF heading and nearby POI landmarks when enabled.
        """
        logInfo("🌍 Geocode Sweep: Filling missing locations from GPS")
        if not self.master_store:
            logWarn("⚠️  MasterStore not configured; cannot run geocode sweep.")
            return

        # Prepare a GeoExtractor with cache_only disabled
        sweep_config = json.loads(json.dumps(self.config))
        sweep_config.setdefault('metadata_extraction', {}).setdefault('geocoding', {})['cache_only'] = False
        extractor = GeoExtractor(sweep_config)

        data = self.master_store.list_paths()
        # Build reverse index of children by source_path
        children_by_source: Dict[str, list] = {}
        for p, e in data.items():
            src = e.get('source_path')
            if src:
                children_by_source.setdefault(src, []).append(p)

        updated = 0
        skipped = 0
        no_gps = 0

        processed = 0
        total = len(data)
        last_pulse = time.time()
        logInfo(f"🔎 Sweep settings — poi_enabled: {getattr(extractor,'poi_enabled', False)}, only_missing: {self.sweep_only_missing}, path_filter: {bool(self.sweep_path_contains)}, limit: {self.sweep_limit or 'none'}")
        try:
            for p, e in list(data.items()):
                # Apply path filter if provided
                if self.sweep_path_contains and self.sweep_path_contains not in p:
                    continue
                gps = e.get('gps')
                has_loc = bool(e.get('location_formatted'))
                if not gps:
                    no_gps += 1
                    continue
                # We still may enrich heading/POIs even if location already present
                lat = gps.get('lat')
                lon = gps.get('lon')
                if lat is None or lon is None:
                    no_gps += 1
                    continue
                try:
                    patch = {}
                    # Only-missing shortcut: if nothing missing and flag set, skip
                    if self.sweep_only_missing and all([
                        has_loc,
                        bool(e.get('heading')) or self.sweep_skip_heading,
                        bool(e.get('landmarks')) or self.sweep_skip_poi
                    ]):
                        skipped += 1
                        continue

                    # Always backfill location if missing
                    if not has_loc:
                        loc = extractor.reverse_geocode(lat, lon)
                        if loc:
                            formatted = extractor.format_location(loc)
                            patch.update({"location": loc, "location_formatted": formatted})

                    # Extract heading from EXIF if missing
                    heading_block = None
                    if not self.sweep_skip_heading:
                        try:
                            from PIL import Image
                            from PIL.ExifTags import TAGS, GPSTAGS
                            import os
                            if os.path.exists(p):
                                img = Image.open(p)
                                exif = img._getexif()
                                gps_info = {}
                                if exif:
                                    for tag, value in exif.items():
                                        decoded = TAGS.get(tag, tag)
                                        if decoded == 'GPSInfo':
                                            for gps_tag in value:
                                                sub_decoded = GPSTAGS.get(gps_tag, gps_tag)
                                                gps_info[sub_decoded] = value[gps_tag]
                                def _convert_rational(val):
                                    if val is None:
                                        return None
                                    try:
                                        if isinstance(val, tuple) and len(val)==2:
                                            num, den = val
                                            den = den or 1
                                            return float(num)/float(den)
                                        return float(val)
                                    except Exception:
                                        return None
                                def _deg_to_cardinal(deg):
                                    if deg is None:
                                        return None
                                    dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
                                    idx = int((deg % 360) / 22.5 + 0.5) % 16
                                    return dirs[idx]
                                if gps_info and not e.get('heading'):
                                    hdg = _convert_rational(gps_info.get('GPSImgDirection'))
                                    if hdg is not None:
                                        heading_block = {
                                            'degrees': hdg,
                                            'cardinal': _deg_to_cardinal(hdg),
                                            'ref': gps_info.get('GPSImgDirectionRef')
                                        }
                                        patch['heading'] = heading_block
                        except Exception:
                            pass

                    # Fetch POIs if enabled and missing
                    if not self.sweep_skip_poi and getattr(extractor, 'poi_enabled', False) and not e.get('landmarks'):
                        heading_deg = (heading_block or e.get('heading') or {}).get('degrees')
                        pois = extractor.fetch_pois(lat, lon, heading_deg=heading_deg)
                        if pois:
                            patch['landmarks'] = pois

                    # Write updates if any
                    if patch:
                        self.master_store.update_entry(p, patch, stage='geocode_sweep')
                        # Propagate to children derived from this source
                        for child in children_by_source.get(p, []):
                            self.master_store.update_entry(child, patch, stage='geocode_sweep')
                        updated += 1
                        if updated % 25 == 0:
                            logInfo(f"  ✓ Updated {updated} entries with locations/POIs/heading...")
                    else:
                        skipped += 1
                    processed += 1
                    # Heartbeat pulse
                    now = time.time()
                    if now - last_pulse >= self.sweep_pulse_sec:
                        logInfo(f"⏳ Sweep progress: {processed}/{total} processed | updated:{updated} skipped:{skipped} no_gps:{no_gps}")
                        last_pulse = now
                    if self.sweep_limit is not None and processed >= self.sweep_limit:
                        logInfo(f"⏹️  Sweep limit reached: processed {processed} entries")
                        break
                except Exception as ex:
                    logWarn(f"⚠️  Geocode sweep failed for {p}: {ex}")
        except KeyboardInterrupt:
            logWarn("🛑 Geocode sweep interrupted by user (Ctrl+C). Partial updates saved.")

        logInfo(f"✅ Geocode sweep complete — updated: {updated}, skipped: {skipped}, no GPS: {no_gps}")
    
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
        output_folder = lora_config.get('output_folder', self.paths.get('lora_processed'))
        
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
        lora_output = lora_config.get('output_folder', self.paths.get('lora_processed'))
        watermark_output = self.paths.get('lora_watermarked') or (self.paths.get('output') and str(Path(self.paths.get('output'))/"lora_wm"))
        
        logInfo(f"📁 Input: {lora_output}")
        logInfo(f"📂 Output: {watermark_output}")
        
        # Call postprocess_lora.py
        import sys
        import subprocess
        
        cmd = [
            sys.executable,
            'postprocess_lora.py',
            '--input', lora_output,
            '--output', watermark_output,
            '--force'  # Always re-watermark when running from pipeline
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
        source_folder = Path(s3_config.get('source_folder', self.paths.get('lora_watermarked')))
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
                        # Upload file (will overwrite if exists)
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

                        # Update master store with deployment info
                        if self.master_store:
                            deploy = {
                                "bucket": bucket_name,
                                "key": s3_key,
                                "region": s3_config.get('region'),
                                "uploaded_at": utc_now_iso_z(),
                                "cache_control": extra_args.get('CacheControl'),
                                "content_type": extra_args.get('ContentType'),
                                "storage_class": extra_args.get('StorageClass'),
                            }
                            self.master_store.update_section(str(image_file), 'deployment', deploy, stage='s3_deployment')
                        
                        if uploaded_files % 10 == 0:
                            logInfo(f"  ✓ Uploaded {uploaded_files} new | {total_files} total files processed...")
                        
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
            'geocode_sweep': self.run_geocode_sweep_stage,
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
    parser.add_argument("--cache-only-geocode", action="store_true", help="Use geocoding cache only (no network calls)")
    # Geocode sweep filters
    parser.add_argument("--sweep-path-contains", help="Only sweep entries whose path contains this substring")
    parser.add_argument("--sweep-limit", type=int, help="Limit number of entries processed in geocode sweep")
    parser.add_argument("--sweep-only-missing", action="store_true", help="Process only entries missing location/heading/POIs")
    parser.add_argument("--sweep-skip-poi", action="store_true", help="Skip POI fetching during sweep")
    parser.add_argument("--sweep-skip-heading", action="store_true", help="Skip EXIF heading extraction during sweep")
    parser.add_argument("--sweep-pulse-sec", type=int, default=5, help="Heartbeat interval in seconds for geocode sweep progress")
    
    args = parser.parse_args()
    
    runner = PipelineRunner(
        args.config,
        cache_only_geocode=args.cache_only_geocode,
        sweep_path_contains=args.sweep_path_contains,
        sweep_limit=args.sweep_limit,
        sweep_only_missing=args.sweep_only_missing,
        sweep_skip_poi=args.sweep_skip_poi,
        sweep_skip_heading=args.sweep_skip_heading,
        sweep_pulse_sec=args.sweep_pulse_sec,
    )
    runner.run_pipeline(args.stages)
