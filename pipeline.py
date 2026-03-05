"""
Pipeline Task Runner
Orchestrates the full photo processing pipeline from Apple Photos export to LoRA processing
"""
import json
import os
import time
import subprocess
import logging
import importlib
from pathlib import Path
from datetime import datetime
from utils.config_utils import resolve_config_placeholders
from utils.time_utils import utc_now_iso_z
from typing import Dict, List
from core.geo_extractor import GeoExtractor
from core.watermark_generator import WatermarkGenerator
from core.watermark_applicator import WatermarkApplicator
from core.image_preprocessor import ImagePreprocessor
from core.master_store import MasterStore
from utils.logger import logInfo, logError, logWarn

# Setup file logging - will be initialized in main() with stage info


def find_images_in_directory(directory: Path) -> List[Path]:
    """
    Find all image files in directory using consistent extension patterns.
    Returns list of image file paths that actually exist.
    """
    extensions = ['jpg', 'jpeg', 'png', 'heic', 'webp']
    image_files = []
    
    for ext in extensions:
        image_files.extend(directory.glob(f'**/*.{ext}'))
        image_files.extend(directory.glob(f'**/*.{ext.upper()}'))
    
    # Filter to only files that actually exist (glob can return broken paths)
    image_files = [f for f in image_files if f.exists() and f.is_file()]
    
    return image_files


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
        force_llm_reanalysis: bool = False,
        force_watermark: bool = False,
        debug: bool = False,
        debug_prompt: bool = False,
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
        self.force_llm_reanalysis = force_llm_reanalysis
        self.force_watermark = force_watermark
        self.debug = debug
        # Store debug_prompt in config for OllamaWatermarkAnalyzer
        self.config.setdefault('llm_image_analysis', {})['debug_prompt'] = debug_prompt
        
    def _load_config(self) -> Dict:
        """Load pipeline configuration"""
        with open(self.config_path, 'r') as f:
            raw = json.load(f)
            return resolve_config_placeholders(raw)
    
    # Legacy catalog removed; MasterStore is authoritative.

    # Master catalog rebuild removed; using incremental MasterStore updates instead.
    
    def _catalog_exported_files(self):
        """Catalog exported files in master store after successful export"""
        if not self.master_store:
            logWarn("⚠️  MasterStore not configured; skipping export cataloging")
            return
        
        export_path = Path(self.paths.get('apple_photos_export'))
        if not export_path.exists():
            logWarn(f"⚠️  Export path does not exist: {export_path}")
            return
        
        image_files = find_images_in_directory(export_path)
        cataloged = 0
        
        for image_path in image_files:
            image_path_str = str(image_path)
            
            # Skip if already cataloged
            if self.master_store.has_stage(image_path_str, 'export'):
                continue
            
            # Extract album name from folder structure
            album_name = None
            try:
                relative = image_path.relative_to(export_path)
                if len(relative.parts) > 1:
                    album_name = relative.parts[0]
            except ValueError:
                pass
            
            # Create initial entry for exported file
            patch = {
                "type": "exported",
                "file_name": image_path.name,
                "file_path": image_path_str,
                "album_name": album_name,
                "export_timestamp": utc_now_iso_z(),
            }
            
            self.master_store.update_entry(image_path_str, patch, stage='export')
            cataloged += 1
        
        if cataloged > 0:
            logInfo(f"📝 Cataloged {cataloged} exported files in master store")
    
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
                
                # Catalog exported files in master store
                self._catalog_exported_files()
            else:
                logError(f"❌ Export failed: {result.stderr}")
                
        except Exception as e:
            logError(f"❌ Export error: {e}")
    
    def run_cleanup_stage(self, stages_to_run: List[str] = None, force_clean: bool = False):
        """Stage 0: Archive and clean pipeline artifacts
        
        Creates a single timestamped archive containing:
        - pipeline/albums
        - pipeline/lora_processed
        - pipeline/metadata
        - pipeline/watermarked
        
        Then cleans (empties) all folders EXCEPT pipeline/archive:
        - pipeline/albums
        - pipeline/lora_processed (user can manually remove if needed)
        - pipeline/metadata
        - pipeline/watermarked
        - pipeline/scaled (NOT archived, just cleaned)
        
        Args:
            stages_to_run: List of stages being executed (unused, always archives)
            force_clean: If True, always clean folders after archiving
        """
        if not self.config.get('cleanup', {}).get('enabled', False):
            logInfo("⏭️  Cleanup stage disabled, skipping...")
            return
        
        logInfo("🧹 Stage 0: Archive and cleanup pipeline artifacts")
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Always archive if configured
        if self.config['cleanup'].get('archive_old_outputs', False):
            import shutil
            
            archive_base = Path(self.paths.get('archive'))
            archive_base.mkdir(parents=True, exist_ok=True)
            
            archive_name = f"pipeline_{timestamp}"
            archive_zip_path = archive_base / f"{archive_name}.zip"
            
            # Define folders to archive
            folders_to_archive = [
                ('albums', Path(self.paths.get('apple_photos_export'))),
                ('lora_processed', Path(self.paths.get('lora_processed'))),
                ('metadata', Path(self.paths.get('metadata_dir'))),
                ('watermarked', Path(self.paths.get('watermarked_final'))),
            ]
            
            # Check which folders have content
            items_to_archive = []
            for folder_name, folder_path in folders_to_archive:
                if folder_path.exists() and any(folder_path.iterdir()):
                    items_to_archive.append((folder_name, folder_path))
            
            if items_to_archive:
                logInfo(f"📦 Creating archive: {archive_name}.zip")
                logInfo(f"   Archiving {len(items_to_archive)} folder(s): {', '.join([f[0] for f in items_to_archive])}")
                
                # Create zip archive directly (no temp directory needed)
                import zipfile
                
                with zipfile.ZipFile(archive_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for folder_name, source_path in items_to_archive:
                        # Walk through folder and add all files
                        for file_path in source_path.rglob('*'):
                            if file_path.is_file():
                                # Create archive path preserving structure
                                arcname = f"{archive_name}/{folder_name}/{file_path.relative_to(source_path)}"
                                zipf.write(file_path, arcname)
                        logInfo(f"  ✓ Added {folder_name}/ to archive")
                
                zip_size_mb = archive_zip_path.stat().st_size / (1024 * 1024)
                logInfo(f"✅ Archive created: {archive_name}.zip ({zip_size_mb:.1f} MB)")
                logInfo(f"   Saved to: {archive_base}/")
            else:
                logInfo("ℹ️  No content to archive (folders empty or don't exist)")
        
        # Clean (empty) all artifact folders EXCEPT lora_processed
        logInfo("\n🗑️  Cleaning artifact folders...")
        
        folders_to_clean = [
            ('albums', Path(self.paths.get('apple_photos_export'))),
            ('metadata', Path(self.paths.get('metadata_dir'))),
            ('watermarked', Path(self.paths.get('watermarked_final'))),
            ('scaled', Path(self.paths.get('preprocessed'))),
        ]
        
        import shutil
        cleaned_count = 0
        
        for folder_name, folder_path in folders_to_clean:
            if folder_path.exists() and any(folder_path.iterdir()):
                # Remove all content
                shutil.rmtree(folder_path)
                folder_path.mkdir(parents=True, exist_ok=True)
                logInfo(f"  ✓ Cleaned {folder_name}/")
                cleaned_count += 1
            else:
                logInfo(f"  ℹ️  Skipped {folder_name}/ (already empty)")
        
        if cleaned_count > 0:
            logInfo(f"\n✅ Cleanup complete - {cleaned_count} folder(s) cleaned and ready for new export")
        else:
            logInfo("\n✅ Cleanup complete - no folders needed cleaning")
        
        logInfo("   NOTE: pipeline/lora_processed is PRESERVED (archived but not cleaned)")
        logInfo("   NOTE: You can manually remove lora_processed if needed")
        logInfo("   NOTE: pipeline/archive is preserved (contains all backups)")

    
    def run_metadata_extraction_stage(self):
        """Stage 2: Extract metadata and geolocation"""
        if not self.config.get('metadata_extraction', {}).get('enabled', False):
            logInfo("⏭️  Metadata extraction disabled, skipping...")
            return
        
        logInfo("🗺️  Stage 2: Extracting metadata and geolocation")
        
        # CLEANUP: Remove stale entries from master.json for files that no longer exist in albums
        # This ensures master.json only contains files from pipeline/albums
        if self.master_store:
            albums_path = Path(self.paths.get('raw_input'))
            stale_count = 0
            for path_key in list(self.master_store.data.keys()):
                # Only check original files (not derivatives)
                entry = self.master_store.data[path_key]
                if entry.get('source_path'):
                    continue
                # Check if file exists in albums folder
                if not Path(path_key).exists():
                    del self.master_store.data[path_key]
                    stale_count += 1
            if stale_count > 0:
                self.master_store.save()
                logInfo(f"🧹 Removed {stale_count} stale entries (files not in albums folder)")
        
        # Legacy catalog retired; skipping reads.
        
        # Force reload geo_extractor module to pick up any code changes
        import core.geo_extractor
        importlib.reload(core.geo_extractor)
        from core.geo_extractor import GeoExtractor
        
        geo_extractor = GeoExtractor(self.config)
        raw_input_path = Path(self.paths.get('raw_input'))
        
        # Process all images in input folder using consistent extension finding
        image_files = find_images_in_directory(raw_input_path)
        
        new_count = 0
        skipped_count = 0
        
        logInfo(f"📊 Found {len(image_files)} images in input folder...")
        
        if len(image_files) == 0:
            logWarn(f"⚠️  No images found in {raw_input_path} - skipping metadata extraction")
            return
        
        for idx, image_path in enumerate(image_files, 1):
            image_path_str = str(image_path)
            
            # ALWAYS re-process when metadata_extraction stage is explicitly run
            # This ensures schema updates and new POI data are applied via upsert
            # Only skip if using sweep filter and image doesn't match
            if self.sweep_path_contains and self.sweep_path_contains not in image_path_str:
                skipped_count += 1
                continue
            
            # PRINT IMAGE NAME SO USER CAN TRACK PROGRESS
            print(f"\n📸 Processing: {image_path.name} ({idx}/{len(image_files)})")
            
            try:
                metadata = geo_extractor.extract_metadata(image_path_str)
                # Write clean, organized metadata to master_store
                # Schema: date_taken (EXIF), gps node (EXIF), location node (Geocoding), nearby_pois (POI enrichment), poi_search (search metadata)
                if self.master_store:
                    # Get existing entry to clean up old fields
                    entry = self.master_store.get(image_path_str)
                    
                    # Remove old deprecated fields
                    if entry and "landmarks" in entry:
                        del entry["landmarks"]
                    
                    # Build complete replacement patch (not merge)
                    # NOTE: nearby_pois and poi_search are NOT stored in master.json
                    # They are cached in geocode_cache.json keyed by GPS coordinates
                    patch = {
                        "date_taken": metadata.get("date_taken"),
                        "date_taken_utc": metadata.get("date_taken_utc"),
                        "gps": metadata.get("gps"),  # Clean GPS node: {lat, lon, altitude, heading, cardinal}
                        "location": metadata.get("location"),  # Geocoding result with formatted string
                    }
                    
                    self.master_store.update_entry(image_path_str, patch, stage='metadata_extraction')
                new_count += 1
                
                if new_count % 10 == 0:
                    print("\n" + "─" * 60)
                    logInfo(f"  Extracted metadata for {new_count} new images...")
                    print("─" * 60 + "\n")
                    
            except Exception as e:
                logWarn(f"⚠️  Failed to extract metadata from {image_path.name}: {e}")
        
        print("\n" + "─" * 60)
        logInfo(f"✅ Metadata extraction complete - {new_count} new, {skipped_count} skipped (existing)")
        print("─" * 60 + "\n")
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
        
        # Check if there are any images to process (consistent with metadata_extraction)
        input_path = Path(raw_input_path)
        if not input_path.exists():
            logWarn(f"⚠️  Input path does not exist: {raw_input_path} - skipping preprocessing")
            return
        
        image_files = find_images_in_directory(input_path)
        if len(image_files) == 0:
            logWarn(f"⚠️  No images found in {raw_input_path} - skipping preprocessing")
            return
        
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
                    location = entry.get('location') or {}
                    existing_catalog[raw_path] = {
                        'date_taken': entry.get('date_taken'),
                        'date_taken_utc': entry.get('date_taken_utc'),
                        'location_formatted': location.get('formatted', 'Unknown'),
                        'location': location,
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
                source_image_path = meta.get("input_path")
                patch = {
                    "type": "preprocessed",
                    "preprocessing": section,
                }
                # Carry through metadata from source if present
                if meta.get('location'):
                    patch['location'] = meta.get('location')
                if meta.get('date_taken'):
                    patch['date_taken'] = meta.get('date_taken')
                if meta.get('date_taken_utc'):
                    patch['date_taken_utc'] = meta.get('date_taken_utc')
                # Store preprocessed output under source entry as derivative
                self.master_store.update_entry(out_path, patch, stage='preprocessing', source_path=source_image_path)
        
        logInfo("✅ Preprocessing complete")
    
    def run_watermarking_stage(self):
        """Stage 5: Apply watermarks before LoRA processing"""
        wm_cfg = self.config.get('watermark', {})
        if not wm_cfg.get('enabled', False):
            logInfo("⏭️  Watermarking disabled, skipping...")
            return

        if not wm_cfg.get('apply_before_lora', True):
            logInfo("⏭️  Pre-LoRA watermarking disabled via apply_before_lora=false")
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
        pre_wm_dir = self.paths.get('pre_lora_watermarked')
        if not pre_wm_dir:
            logWarn("⚠️  No pre-LoRA watermark directory configured (paths.pre_lora_watermarked)")
            return
        watermarked_path = Path(pre_wm_dir)
        
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
                e_location = (entry or {}).get('location', {})
                if entry and not e_location.get('formatted') and entry.get('source_path'):
                    src_entry = self.master_store.get(entry.get('source_path'))
                e = entry or {}
                s = src_entry or {}
                s_location = s.get('location', {})
                meta_for_wm = {
                    'location_formatted': e_location.get('formatted') or s_location.get('formatted'),
                    'date_taken_utc': e.get('date_taken_utc') or s.get('date_taken_utc'),
                    'date_taken': e.get('date_taken') or s.get('date_taken'),
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
                    source_image_path = str(image_path)
                    patch = {
                        "type": "watermarked",
                        "watermark": wm_block,
                    }
                    # Store watermarked output under source entry as derivative
                    self.master_store.update_entry(str(output_file), patch, stage='watermarking', source_path=source_image_path)
                
                watermarked_count += 1
                
                if watermarked_count % 10 == 0:
                    logInfo(f"  Watermarked {watermarked_count} images...")
                
            except Exception as e:
                logWarn(f"⚠️  Failed to watermark {image_path.name}: {e}")
        
        logInfo(f"✅ Watermarking complete - {watermarked_count} images processed")

    def run_llm_image_analysis_stage(self):
        """Stage: Generate AI-powered image analysis using vision LLM.

        Uses enhanced Ollama 6-stage pipeline if available, falls back to simple analysis.
        Generates GPS-grounded watermarks with POI context and street research.
        """
        llm_config = self.config.get('llm_image_analysis', {})
        vision_model = llm_config.get('vision_model', llm_config.get('model', 'unknown'))
        logInfo(f"🤖 LLM Image Analysis: Generating AI descriptions with vision model ({vision_model})")
        if not self.master_store:
            logWarn("⚠️  MasterStore not configured; cannot run LLM analysis.")
            return

        # Check if enhanced LLM pipeline is available
        use_enhanced = False
        analyzer = None
        
        if llm_config.get('enabled', False):
            try:
                from core.ollama_watermark_analyzer import OllamaWatermarkAnalyzer
                # Pass geocode cache path so analyzer can lookup POI data
                metadata_dir = Path(self.paths.get('metadata_dir', '/Volumes/MySSD/skicyclerun.i2i/pipeline/metadata'))
                geocode_cache_path = metadata_dir / "geocode_cache.json"
                analyzer = OllamaWatermarkAnalyzer(self.config, str(geocode_cache_path))
                use_enhanced = True
                logInfo("✅ Using enhanced 6-stage LLM pipeline (GPS-grounded POI research)")
            except (ImportError, ConnectionError) as e:
                logWarn(f"⚠️  Enhanced LLM pipeline not available: {e}")
                logInfo("   Falling back to simple analysis")
        
        # Fall back to simple analyzer if enhanced not available
        if not use_enhanced:
            llm_config = self.config.get('llm_image_analysis', {})
            if llm_config.get('enabled', True):
                try:
                    from core.llm_image_analyzer import LLMImageAnalyzer
                    analyzer = LLMImageAnalyzer(
                        endpoint=llm_config.get('endpoint', 'http://localhost:11434'),
                        model=llm_config.get('model', 'ministral-3:8b')
                    )
                except Exception as e:
                    logError(f"❌ Cannot initialize LLM analyzer: {e}")
                    return

        data = self.master_store.list_paths()
        # Build reverse index of children by source_path
        children_by_source: Dict[str, list] = {}
        for p, e in data.items():
            src = e.get('source_path')
            if src:
                children_by_source.setdefault(src, []).append(p)

        updated = 0
        skipped = 0
        no_image = 0

        processed = 0
        
        # Pre-scan to count valid images (originals that exist and pass filters)
        # Also clean up stale entries for files that no longer exist
        valid_images = []
        stale_entries = []
        for p, e in data.items():
            # Skip derivatives
            if e.get('source_path'):
                continue
            # Apply path filter if provided
            if self.sweep_path_contains and self.sweep_path_contains not in p:
                continue
            # Check if file exists
            if Path(p).exists():
                valid_images.append((p, e))
            else:
                no_image += 1
                stale_entries.append(p)
        
        # Remove stale entries from master.json (files that don't exist)
        if stale_entries and self.master_store:
            for stale_path in stale_entries:
                if stale_path in self.master_store.data:
                    del self.master_store.data[stale_path]
            self.master_store.save()
            logInfo(f"🧹 Removed {len(stale_entries)} stale entries from master store")
                
        total = len(valid_images)
        total_derivatives = sum(1 for e in data.values() if e.get('source_path'))
        last_pulse = time.time()
        logInfo(f"🔎 Analysis settings — path_filter: {bool(self.sweep_path_contains)}, limit: {self.sweep_limit or 'none'}")
        logInfo(f"📊 Processing {total} original images (skipping {total_derivatives} derivatives)")
        
        try:
            for p, e in valid_images:
                    
                try:
                    # Skip if already has LLM analysis (unless force flag is set)
                    if e.get('llm_image_analysis') and not self.force_llm_reanalysis:
                        skipped += 1
                        processed += 1
                        continue
                    
                    patch = {}

                    # Extract context from metadata (POI data NOT stored in master.json anymore)
                    location = e.get('location', {})
                    gps = e.get('gps', {})
                    location_formatted = location.get('formatted', 'Unknown Location')
                    nearby_pois = []  # POI data not stored in master.json - empty list for fallback
                    
                    # Log analysis context with clear separator
                    print("\n" + "─" * 80)
                    logInfo(f"🤖 Analyzing: {Path(p).name} | Location: {location_formatted}")
                    
                    result = None
                    
                    # Run enhanced or simple analysis
                    if use_enhanced:
                        # Enhanced 6-stage Ollama pipeline (looks up POIs from geocode cache internally)
                        try:
                            metadata_for_analysis = {
                                'location': location,
                                'gps': gps
                            }
                            result = analyzer.analyze(p, metadata_for_analysis)
                        except Exception as e:
                            logWarn(f"⚠️  Enhanced analysis failed: {e}, falling back to simple")
                            use_enhanced = False  # Disable for remaining images
                    
                    if not use_enhanced and analyzer:
                        # Simple LLM analysis fallback - use LLMImageAnalyzer instead
                        try:
                            from core.llm_image_analyzer import LLMImageAnalyzer
                            
                            debug_path = None
                            if self.debug:
                                metadata_dir = Path(self.paths.get('lib_root')) / 'pipeline' / 'metadata'
                                debug_path = metadata_dir / 'llm_prompt_request.json'
                            
                            # Use simple analyzer for fallback
                            llm_config = self.config.get('llm_image_analysis', {})
                            simple_analyzer = LLMImageAnalyzer()
                            result = simple_analyzer.analyze_image(
                                image_path=p,
                                nearby_pois=[],
                                location=location,
                                gps=gps,
                                poi_search={},
                                timeout=llm_config.get('timeout', 30),
                                debug_output_path=str(debug_path) if debug_path else None
                            )
                            
                            if not result and llm_config.get('fallback_on_error', True):
                                date_taken = e.get('date_taken', '')
                                result = analyzer.generate_fallback(
                                    location_formatted=location_formatted,
                                    nearby_pois=nearby_pois,
                                    date_taken=date_taken
                                )
                        except Exception as llm_err:
                            logWarn(f"⚠️  Simple LLM analysis failed: {llm_err}")
                            if self.config.get('llm_image_analysis', {}).get('fallback_on_error', True):
                                from core.llm_image_analyzer import LLMImageAnalyzer
                                simple_analyzer = LLMImageAnalyzer()
                                result = simple_analyzer.generate_fallback(
                                    location_formatted=location_formatted,
                                    nearby_pois=nearby_pois,
                                    date_taken=e.get('date_taken', '')
                                )
                    
                    # Store result if available
                    if result:
                        # Check if we got actual content or just empty fields
                        # Extract key fields for logging
                        travel_blog = result.get('travel_blog', '')
                        summary = result.get('summary', '')
                        programmatic_watermark = result.get('programmatic_watermark', '')
                        writing_style = result.get('writing_style', '')
                        primary = result.get('primary_subject', '')
                        analysis_time = result.get('llm_analysis_time', 0)
                        
                        # Check if content generation succeeded
                        has_content = bool(travel_blog or summary or programmatic_watermark)
                        
                        # If content generation failed (all text fields empty), generate fallback
                        if not has_content and primary:
                            logInfo(f"⚠️  Content generation returned empty - generating fallback")
                            
                            # Generate meaningful fallback content
                            fallback_watermark = primary  # Use the primary subject
                            fallback_summary = f"{primary} in {location_formatted}"
                            fallback_blog = f"A scene captured in {location_formatted}, featuring {primary.lower()}."
                            
                            # Update result with fallback content
                            result['watermark_text'] = fallback_watermark
                            result['summary'] = fallback_summary
                            result['travel_blog'] = fallback_blog
                            
                            logInfo(f"📝 Fallback: \"{fallback_watermark[:60]}...\"")
                        elif has_content:
                            # Show success message with writing style
                            style_info = f" | Style: {writing_style}" if writing_style else ""
                            logInfo(f"✨ Generated: \"{summary[:80]}...\" | Time: {analysis_time:.1f}s{style_info}")
                        else:
                            logInfo(f"⚠️  No content generated (missing primary subject)")
                        
                        patch['llm_image_analysis'] = result

                    # Write updates if any
                    if patch:
                        self.master_store.update_entry(p, patch, stage='llm_image_analysis')
                        # Propagate to children derived from this source
                        for child in children_by_source.get(p, []):
                            self.master_store.update_entry(child, patch, stage='llm_image_analysis')
                        updated += 1
                        if updated % 10 == 0:
                            logInfo(f"  ✓ Analyzed {updated} images...")
                    else:
                        skipped += 1
                    
                    processed += 1
                    
                    # Heartbeat pulse
                    now = time.time()
                    if now - last_pulse >= self.sweep_pulse_sec:
                        logInfo(f"⏳ Analysis progress: {processed}/{total} processed | updated:{updated} skipped:{skipped} no_image:{no_image}")
                        last_pulse = now
                    
                    if self.sweep_limit is not None and processed >= self.sweep_limit:
                        logInfo(f"⏹️  Analysis limit reached: processed {processed} entries")
                        break
                        
                except Exception as ex:
                    logWarn(f"⚠️  LLM analysis failed for {p}: {ex}")
                    
        except KeyboardInterrupt:
            logWarn("🛑 LLM analysis interrupted by user (Ctrl+C). Partial updates saved.")

        logInfo(f"✅ LLM analysis complete — updated: {updated}, skipped: {skipped}, no image: {no_image}")
        if use_enhanced:
            logInfo(f"   Enhanced Ollama pipeline used with GPS-grounded POI research")
    
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
        
        # Use resolved paths from self.paths (already processed by resolve_config_placeholders)
        input_folder = str(Path(self.paths.get('preprocessed')))
        output_folder = str(Path(self.paths.get('lora_processed')))
        
        # Show relative paths for cleaner output
        lib_root = self.paths.get('lib_root')
        input_rel = input_folder.replace(lib_root + '/', '') if lib_root else input_folder
        output_rel = output_folder.replace(lib_root + '/', '') if lib_root else output_folder
        
        logInfo(f"📁 Input: {input_rel}")
        logInfo(f"📂 Output: {output_rel}")
        logInfo(f"🎨 Processing {len(loras_to_process)} LoRA styles: {', '.join(loras_to_process)}")
        
        # Import main.py functions
        import sys
        import subprocess
        
        for lora_name in loras_to_process:
            # Check for stop file before starting each LoRA
            stop_file = "/tmp/skicyclerun_stop"
            if os.path.exists(stop_file):
                from datetime import datetime
                stop_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                logInfo("\n" + "=" * 80)
                logInfo(f"🛑 STOP FILE DETECTED: {stop_file}")
                logInfo(f"⏰ Stop requested at: {stop_time}")
                logInfo(f"📊 Progress: Completed processing for previous LoRAs")
                logInfo("✅ Gracefully shutting down pipeline")
                logInfo("=" * 80)
                try:
                    os.remove(stop_file)
                    logInfo(f"🗑️  Stop file removed: {stop_file}")
                except Exception as e:
                    logWarn(f"⚠️  Could not remove stop file {stop_file}: {e}")
                logInfo(f"👋 Pipeline stopped at {stop_time}")
                return  # Exit the LoRA processing stage
            
            logInfo("=" * 80)
            logInfo(f"🎨 STARTING LoRA PROCESSING: {lora_name}")
            logInfo(f"📂 Input folder: {input_rel}")
            logInfo(f"📂 Output folder: {output_rel}")
            logInfo("=" * 80)
            
            # Call LoRA transformer with batch processing
            cmd = [
                sys.executable, 
                'core/lora_transformer.py',
                '--lora', lora_name,
                '--batch',
                '--input-folder', input_folder,
                '--output-folder', output_folder
            ]
            
            try:
                # Let stdout/stderr stream directly for progress and timing
                # Pass environment to ensure UI-set variables are inherited
                result = subprocess.run(cmd, check=True, text=True, env=os.environ.copy())
                logInfo(f"\n✅ {lora_name} processing complete")
            except subprocess.CalledProcessError as e:
                logError(f"\n❌ {lora_name} processing failed: {e}")
                if e.stderr:
                    logError(f"Error output:\n{e.stderr}")
                logError(f"❌ Pipeline stopped due to LoRA processing failure")
                raise  # Stop pipeline on failure
        
        logInfo(f"✅ LoRA processing complete - {len(loras_to_process)} styles processed")
    
    def run_post_lora_watermarking_stage(self):
        """Stage 7: Apply watermarks to LoRA-processed images (catalog-driven)"""
        logInfo("💧 Stage 7: Watermarking LoRA-processed images")
        
        from core.watermark_generator import WatermarkGenerator
        from core.watermark_applicator import WatermarkApplicator
        from core.copyright_embedder import CopyrightEmbedder
        
        # Use resolved paths
        lora_folder = Path(self.paths.get('lora_processed'))
        output_folder = Path(self.paths.get('watermarked_final'))
        
        if not output_folder:
            logWarn("⚠️  No final albums directory configured (paths.final_albums)")
            return
        
        if not lora_folder.exists():
            logError(f"❌ LoRA input folder not found: {lora_folder}")
            return
        
        # Show relative paths
        lib_root = self.paths.get('lib_root')
        input_rel = str(lora_folder).replace(lib_root + '/', '') if lib_root else str(lora_folder)
        output_rel = str(output_folder).replace(lib_root + '/', '') if lib_root else str(output_folder)
        
        logInfo(f"📁 Input: {input_rel}")
        logInfo(f"📂 Output: {output_rel}")
        
        # Initialize watermark tools
        watermark_config = self.config.get('watermark', {}).copy()
        watermark_config['enabled'] = True
        temp_config = self.config.copy()
        temp_config['watermark'] = watermark_config
        
        watermark_gen = WatermarkGenerator(temp_config)
        watermark_app = WatermarkApplicator(temp_config)
        
        copyright_enabled = self.config.get('copyright', {}).get('enabled', False)
        copyright_embedder = CopyrightEmbedder(temp_config) if copyright_enabled else None
        
        # Scan lora_processed folder for actual LoRA images
        processed = 0
        watermarked = 0
        skipped = 0
        failed = 0
        
        lora_images = find_images_in_directory(lora_folder)
        
        logInfo(f"📊 Found {len(lora_images)} LoRA-processed images")
        
        for lora_path in lora_images:
            # Extract original filename from LoRA filename
            # Pattern: {original}_{style}_{timestamp}.webp or {original}_{style}.webp
            lora_stem = lora_path.stem
            parts = lora_stem.rsplit('_', 2)
            
            # Try to find the original image name
            if len(parts) >= 2:
                # Try removing timestamp if present
                if len(parts) == 3 and parts[-1].isdigit() and len(parts[-1]) == 8:
                    original_stem = parts[0]
                    style_name = parts[1]
                else:
                    original_stem = '_'.join(parts[:-1])
                    style_name = parts[-1]
            else:
                original_stem = lora_stem
                style_name = 'unknown'
            
            # Find source metadata in master_store by matching stem
            source_metadata = None
            source_path = None
            for path_str, entry in self.master_store.list_paths().items():
                if Path(path_str).stem == original_stem:
                    source_metadata = entry
                    source_path = path_str
                    break
            
            if not source_metadata:
                logWarn(f"⚠️  No source metadata found for {lora_path.name} (looking for {original_stem})")
                failed += 1
                continue
                
            # Create output path
            album_name = lora_path.parent.name
            output_album = output_folder / album_name
            output_album.mkdir(parents=True, exist_ok=True)
            output_file = output_album / lora_path.name
            
            # Check if already watermarked (skip unless force flag set)
            if output_file.exists() and not self.force_watermark:
                skipped += 1
                continue
            
            processed += 1
            
            try:
                # Load LoRA generation metadata from master.json (where lora_transformer.py saved it)
                # Data is stored in source_metadata under lora_generations.{style_name}
                lora_generation_params = source_metadata.get('lora_generations', {}).get(style_name, {})
                
                if not lora_generation_params:
                    logWarn(f"⚠️  No LoRA generation metadata found for {lora_path.name}")
                    logWarn(f"   Looking in: master.json['{Path(source_path).name}']['lora_generations.{style_name}']")
                    logWarn(f"   Available lora_generations: {list(source_metadata.get('lora_generations', {}).keys())}")
                    lora_generation_params = {}
                else:
                    logInfo(f"✓ Loaded LoRA metadata: seed={lora_generation_params.get('seed')}, steps={lora_generation_params.get('num_inference_steps')}")
                
                # ============================================
                # WATERMARK ASSEMBLY (SINGLE SOURCE OF TRUTH)
                # ============================================
                
                # LINE 1: Get summary from LLM analysis (one-sentence description in author's style)
                llm_analysis = source_metadata.get('llm_image_analysis', {})
                line1_text = llm_analysis.get('summary', '').strip()
                
                # LINE 2: Get programmatic watermark (city, state, emoji, copyright)
                line2_text = llm_analysis.get('programmatic_watermark', '').strip()
                
                # If no programmatic watermark, build fallback from location + copyright
                if not line2_text:
                    location = source_metadata.get('location', {})
                    location_formatted = location.get('formatted', 'Unknown Location')
                    
                    # Get copyright format from config
                    copyright_config = watermark_config.get('copyright_line', {})
                    copyright_format = copyright_config.get('format', 'SkiCycleRun © {year} {symbol}')
                    fixed_year = watermark_config.get('fixed_year')
                    year = fixed_year if fixed_year else datetime.now().year + watermark_config.get('year_offset', 1)
                    symbol = watermark_config.get('symbol', '▲')
                    copyright_text = copyright_format.format(year=year, symbol=symbol)
                    
                    line2_text = f"{location_formatted} {copyright_text}"
                
                # Add seed to line2 if available
                seed_value = lora_generation_params.get('seed')
                if seed_value:
                    line2_text = f"{line2_text}  🎲 {seed_value}"
                
                # LOG TO TERMINAL
                print(f"\n💧 Watermarking: {lora_path.name}")
                print(f"   🏷️  LINE 1 (Summary): {line1_text}")
                print(f"   🏷️  LINE 2 (Programmatic): {line2_text}")
                if seed_value:
                    print(f"   🎲 Seed: {seed_value}")
                
                # Apply watermark (clean signature - just line1 and line2)
                watermark_app.apply_watermark(
                    image_path=str(lora_path),
                    line1_text=line1_text,
                    line2_text=line2_text,
                    output_path=str(output_file)
                )
                    
                # Embed copyright if enabled
                if copyright_embedder:
                    # Build minimal metadata dict for copyright embedding
                    copyright_metadata = {
                        'location': source_metadata.get('location'),
                        'date_taken_utc': source_metadata.get('date_taken_utc'),
                        'date_taken': source_metadata.get('date_taken')
                    }
                    copyright_embedder.embed_copyright_metadata(
                        str(output_file),
                        str(output_file),
                        copyright_metadata
                    )
                
                # Record watermark application with full LoRA generation metadata
                font_cfg = watermark_config.get('font', {})
                watermark_patch = {
                    'lora_path': str(lora_path),
                    'output_path': str(output_file),
                    'style': style_name,
                    'seed': lora_generation_params.get('seed'),
                    'prompt': lora_generation_params.get('prompt'),
                    'negative_prompt': lora_generation_params.get('negative_prompt'),
                    'num_inference_steps': lora_generation_params.get('num_inference_steps'),
                    'guidance_scale': lora_generation_params.get('guidance_scale'),
                    'device': lora_generation_params.get('device'),
                    'precision': lora_generation_params.get('precision'),
                    'source_image': lora_generation_params.get('source_image'),
                    'generated_at': lora_generation_params.get('generated_at'),
                    'watermark_sources': {
                        'line1': 'llm_image_analysis.summary',
                        'line2': 'llm_image_analysis.programmatic_watermark'
                    },
                    'layout': watermark_config.get('layout', 'two_line'),
                    'font_size': font_cfg.get('size'),
                    'position': watermark_config.get('position'),
                    'applied_at': utc_now_iso_z()
                }
                
                # Update the source entry with watermark info
                if source_path:
                    patch = {
                        f'lora_watermarks.{style_name}': watermark_patch
                    }
                    self.master_store.update_entry(source_path, patch, stage='post_lora_watermarking')
                
                watermarked += 1
                
                print(f"   ✅ Watermarked successfully → {output_file.name}\n")
                
                if watermarked % 10 == 0:
                    logInfo(f"  💧 Watermarked {watermarked} images...")
                    
            except Exception as e:
                logWarn(f"⚠️  Failed to watermark {lora_path.name}: {e}")
                failed += 1
        
        logInfo(f"\n✅ Watermarking complete!")
        logInfo(f"   Processed: {processed}")
        logInfo(f"   Watermarked: {watermarked}")
        logInfo(f"   Skipped: {skipped} (already done)")
        logInfo(f"   Failed: {failed}")
        logInfo(f"   Output: {output_rel}")
    
    def _find_source_metadata_for_lora(self, lora_entry: dict, lora_path: Path) -> dict:
        """Find metadata from original source image for LoRA-processed image"""
        # Try to extract original filename from LoRA filename
        # Pattern: {original}_{style}_{timestamp}.webp
        filename_base = lora_path.stem
        parts = filename_base.rsplit('_', 2)
        
        if len(parts) == 3 and parts[-1].isdigit() and len(parts[-1]) == 8:
            original_base = parts[0]
        else:
            original_base = filename_base
        
        # Search for preprocessed or raw source with matching base name
        preprocessed_folder = Path(self.paths.get('preprocessed'))
        album_name = lora_path.parent.name
        
        # Try preprocessed first
        for ext in ['.webp', '.jpg', '.jpeg', '.png']:
            candidate = preprocessed_folder / album_name / f"{original_base}{ext}"
            entry = self.master_store.get(str(candidate))
            if entry:
                return {
                    'location_formatted': entry.get('location_formatted'),
                    'location': entry.get('location'),
                    'date_taken_utc': entry.get('date_taken_utc'),
                    'date_taken': entry.get('date_taken'),
                    'llm_image_analysis': entry.get('llm_image_analysis'),
                    'landmarks': entry.get('landmarks')
                }
        
        # Fallback: search all entries by stem
        for path_str, entry in self.master_store.list_paths().items():
            if Path(path_str).stem == original_base:
                return {
                    'location_formatted': entry.get('location_formatted'),
                    'location': entry.get('location'),
                    'date_taken_utc': entry.get('date_taken_utc'),
                    'date_taken': entry.get('date_taken'),
                    'llm_image_analysis': entry.get('llm_image_analysis'),
                    'landmarks': entry.get('landmarks')
                }
        
        logWarn(f"⚠️  No source metadata found for {lora_path.name}")
        return {}
    
    def run_s3_deployment_stage(self):
        """Stage 8: Deploy watermarked images to AWS S3"""
        if not self.config.get('s3_deployment', {}).get('enabled', False):
            logInfo("⏭️  S3 deployment disabled, skipping...")
            return
        
        logInfo("☁️  Stage 8: Deploying to AWS S3")
        
        s3_config = self.config.get('s3_deployment', {})
        source_folder_cfg = s3_config.get('source_folder', self.paths.get('final_albums'))
        if not source_folder_cfg:
            logError("❌ No source folder configured for S3 deployment (s3_deployment.source_folder)")
            return
        source_folder = Path(source_folder_cfg)
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
        
        # Check if Ollama is needed and available
        ollama_stages = ['llm_image_analysis', 'post_lora_watermarking']
        needs_ollama = any(stage in stages for stage in ollama_stages)
        
        if needs_ollama:
            ollama_config = self.config.get('ollama', {})
            if ollama_config.get('enabled', False):
                endpoint = ollama_config.get('endpoint', 'http://localhost:11434')
                logInfo(f"🤖 Checking Ollama availability at {endpoint}...")
                
                try:
                    import requests
                    response = requests.get(f"{endpoint}/api/tags", timeout=3)
                    if response.status_code == 200:
                        logInfo(f"✅ Ollama is available")
                    else:
                        logError(f"❌ Ollama endpoint responded with status {response.status_code}")
                        logError(f"💡 Please start Ollama before running stages that require it: {', '.join([s for s in ollama_stages if s in stages])}")
                        return
                except requests.exceptions.ConnectionError:
                    logError(f"❌ Cannot connect to Ollama at {endpoint}")
                    logError(f"💡 Please start Ollama (e.g., 'ollama serve') before running these stages: {', '.join([s for s in ollama_stages if s in stages])}")
                    return
                except requests.exceptions.Timeout:
                    logError(f"❌ Ollama connection timed out at {endpoint}")
                    logError(f"💡 Please check if Ollama is running and accessible")
                    return
                except Exception as e:
                    logError(f"❌ Error checking Ollama availability: {e}")
                    logError(f"💡 Please ensure Ollama is running at {endpoint}")
                    return
        
        # Get force_clean flag from args if available
        force_clean = getattr(self, '_force_clean', False)
        
        # CRITICAL: Ensure cleanup ALWAYS runs BEFORE export (prevents data loss)
        # If both export and cleanup are in stages, reorder so cleanup comes first
        if 'export' in stages and 'cleanup' in stages:
            cleanup_idx = stages.index('cleanup')
            export_idx = stages.index('export')
            if export_idx < cleanup_idx:
                # Export is before cleanup - WRONG ORDER! Fix it
                logWarn("⚠️  Detected cleanup AFTER export - reordering to prevent data loss...")
                stages.remove('cleanup')
                stages.insert(export_idx, 'cleanup')
                logInfo(f"✅ Reordered stages: cleanup will run BEFORE export")
        
        # Auto-run cleanup before export if export is requested and cleanup isn't already in stages
        if 'export' in stages and 'cleanup' not in stages:
            if self.config.get('cleanup', {}).get('enabled', False):
                logInfo("\n" + "=" * 80)
                logInfo(f"▶️  STAGE: CLEANUP (AUTO - BEFORE EXPORT)")
                logInfo("=" * 80)
                self.run_cleanup_stage(stages, force_clean=force_clean)
        
        stage_map = {
            'export': self.run_export_stage,
            'cleanup': lambda: self.run_cleanup_stage(stages, force_clean=force_clean),
            'metadata_extraction': self.run_metadata_extraction_stage,
            'llm_image_analysis': self.run_llm_image_analysis_stage,
            'preprocessing': self.run_preprocessing_stage,
            'watermarking': self.run_watermarking_stage,
            'lora_processing': self.run_lora_processing_stage,
            'post_lora_watermarking': self.run_post_lora_watermarking_stage,
            's3_deployment': self.run_s3_deployment_stage
        }
        
        for stage in stages:
            if stage in stage_map:
                # Log stage header
                logInfo("\n" + "=" * 80)
                logInfo(f"▶️  STAGE: {stage.upper().replace('_', ' ')}")
                logInfo("=" * 80)
                stage_map[stage]()
            else:
                logWarn(f"⚠️  Unknown stage: {stage}")
        
        logInfo("\n" + "=" * 80)
        logInfo("🎉 Pipeline complete!")
        logInfo("=" * 80)
        
        # Suggest next stages based on what was just completed
        self._suggest_next_stages(stages)
    
    def _suggest_next_stages(self, completed_stages: List[str]):
        """Suggest logical next stages based on what was just completed"""
        # Define the natural pipeline progression
        pipeline_sequence = [
            'cleanup',
            'export',
            'metadata_extraction',
            'llm_image_analysis',
            'preprocessing',
            'lora_processing',
            'post_lora_watermarking',
            's3_deployment'
        ]
        
        # Find the last completed stage in the sequence
        last_completed_idx = -1
        for stage in completed_stages:
            if stage in pipeline_sequence:
                idx = pipeline_sequence.index(stage)
                if idx > last_completed_idx:
                    last_completed_idx = idx
        
        # Suggest next stages
        if last_completed_idx >= 0 and last_completed_idx < len(pipeline_sequence) - 1:
            next_stage = pipeline_sequence[last_completed_idx + 1]
            
            # Build suggestion message
            logInfo("\n💡 Suggested next step:")
            logInfo(f"   python pipeline.py --stages {next_stage}")
            
            # Provide context for the next stage
            stage_descriptions = {
                'metadata_extraction': '   Extract EXIF metadata and GPS coordinates from exported images',
                'llm_image_analysis': '   Analyze images with vision LLM to generate descriptions and watermarks',
                'preprocessing': '   Resize and optimize images for LoRA processing',
                'lora_processing': '   Apply artistic style filters with FLUX LoRA models',
                'post_lora_watermarking': '   Add watermarks to LoRA-processed images',
                's3_deployment': '   Deploy final images to AWS S3'
            }
            
            if next_stage in stage_descriptions:
                logInfo(f"   ({stage_descriptions[next_stage]})")
            
            # Show multi-stage option if there are 2+ remaining stages
            remaining_stages = pipeline_sequence[last_completed_idx + 1:]
            if len(remaining_stages) > 1:
                logInfo(f"\n   Or run remaining stages:")
                logInfo(f"   python pipeline.py --stages {' '.join(remaining_stages)}")
        elif last_completed_idx == len(pipeline_sequence) - 1:
            # All stages complete
            logInfo("\n✅ All pipeline stages complete!")
            logInfo("   Your images are fully processed and deployed to S3")

    def check_config(self, stages_requested: List[str] = None) -> bool:
        """Report key path status and ensure required directories exist.
        
        Args:
            stages_requested: Optional list of stages to validate. If provided,
                            only validates paths needed for those stages.
        """
        # Determine if this is export-only validation
        # Note: export automatically runs cleanup, so export-only needs both export + cleanup paths
        is_export_only = stages_requested == ['export']
        is_cleanup_only = stages_requested == ['cleanup']
        
        # If export is requested, cleanup runs automatically, so we need to validate cleanup paths too
        stages_with_implicit = list(stages_requested or [])
        if stages_requested and 'export' in stages_requested and 'cleanup' not in stages_requested:
            stages_with_implicit.append('cleanup')
        path_specs: List[Dict] = []
        lib_root = self.paths.get('lib_root')
        huggingface_cache = self.paths.get('huggingface_cache')
        
        # Always validate library root
        path_specs.append({"label": "Library root", "path": lib_root, "type": "dir", "optional": False, "create": True})
        
        # HuggingFace cache only needed for LoRA processing
        needs_hf_cache = not is_export_only and not is_cleanup_only
        path_specs.append({"label": "HuggingFace cache", "path": huggingface_cache, "type": "dir", "optional": not needs_hf_cache, "create": needs_hf_cache})

        # Core pipeline directories
        for label, key in [
            ("Apple Photos export", 'apple_photos_export'),
            ("Raw input", 'raw_input'),
            ("Preprocessed", 'preprocessed'),
            ("Watermarked (pre-LoRA)", 'pre_lora_watermarked'),
            ("LoRA processed", 'lora_processed'),
            ("Final albums", 'final_albums'),
            ("Archive", 'archive'),
        ]:
            path_specs.append({"label": label, "path": self.paths.get(key), "type": "dir", "optional": False, "create": True})

        # Master catalog file – create parent only
        path_specs.append({
            "label": "Master catalog", 
            "path": self.paths.get('master_catalog'),
            "type": "file",
            "optional": True,
            "create": False,
            "ensure_parent": True,
        })

        # Export script validation - required only if export stage is requested
        if is_export_only or not stages_requested or 'export' in stages_with_implicit:
            export_script = self.config.get('export', {}).get('script_path')
            path_specs.append({"label": "Export AppleScript", "path": export_script, "type": "file", "optional": False, "create": False})

        # Geocode cache file parent path
        cache_file = self.config.get('metadata_extraction', {}).get('geocoding', {}).get('cache_file')
        if cache_file:
            path_specs.append({
                "label": "Geocode cache", 
                "path": cache_file,
                "type": "file",
                "optional": True,
                "create": False,
                "ensure_parent": True,
            })

        # LoRA settings - only validate if LoRA processing stage is requested
        needs_lora = not is_export_only and not is_cleanup_only and (not stages_requested or 'lora_processing' in stages_with_implicit)
        if needs_lora:
            lora_cfg = self.config.get('lora_processing', {})
            path_specs.append({"label": "LoRA input", "path": lora_cfg.get('input_folder'), "type": "dir", "optional": False, "create": True})
            path_specs.append({"label": "LoRA output", "path": lora_cfg.get('output_folder'), "type": "dir", "optional": False, "create": True})
            registry_path = lora_cfg.get('registry_path')
            if registry_path:
                path_specs.append({"label": "LoRA registry", "path": registry_path, "type": "file", "optional": False, "create": False})

        results = []
        has_errors = False
        for spec in path_specs:
            entry = spec.copy()
            target = spec.get('path')
            if not target:
                entry['exists_after'] = False
                entry['existed_before'] = False
                entry['status_note'] = 'unset'
                if not spec.get('optional', False):
                    has_errors = True
                results.append(entry)
                continue

            path_obj = Path(target)
            entry['existed_before'] = path_obj.exists()
            try:
                if spec.get('create') and spec.get('type') == 'dir':
                    path_obj.mkdir(parents=True, exist_ok=True)
                elif spec.get('ensure_parent'):
                    path_obj.parent.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                entry['error'] = str(exc)
                has_errors = True

            entry['exists_after'] = path_obj.exists()
            if not entry['exists_after'] and not spec.get('optional', False) and not entry.get('error') and spec.get('type') == 'dir':
                has_errors = True
            results.append(entry)

        logInfo("\n🧪 PIPELINE CONFIG CHECK")
        env_root = os.getenv("SKICYCLERUN_LIB_ROOT")
        if env_root:
            logInfo(f"        🌱 SKICYCLERUN_LIB_ROOT: {env_root}")
        else:
            logInfo("        🌱 SKICYCLERUN_LIB_ROOT: (not set; using config fallback)")
        if lib_root:
            logInfo(f"        📁 Resolved lib_root: {lib_root}")
        env_cache = os.getenv("HUGGINGFACE_CACHE_LIB")
        hf_home = os.getenv("HF_HOME")
        hf_cache = os.getenv("HUGGINGFACE_CACHE")
        transformers_cache = os.getenv("TRANSFORMERS_CACHE")

        if env_cache:
            logInfo(f"        🧠 HUGGINGFACE_CACHE_LIB: {env_cache}")
        if hf_home:
            logInfo(f"        🧠 HF_HOME: {hf_home}")
        if hf_cache and hf_cache != env_cache:
            logInfo(f"        🧠 HUGGINGFACE_CACHE: {hf_cache}")
        if transformers_cache:
            logInfo(f"        🧠 TRANSFORMERS_CACHE: {transformers_cache}")
        if not any([env_cache, hf_home, hf_cache, transformers_cache]):
            logInfo("        🧠 Hugging Face cache env vars: (none set; using config fallback)")
        if huggingface_cache:
            logInfo(f"        🗂️ HuggingFace cache (resolved): {huggingface_cache}")
        
        # Show local_files_only setting for LoRA processing
        if needs_lora:
            local_files_only = self.config.get("local_files_only", True)
            mode_icon = "🔒" if local_files_only else "🌐"
            mode_text = "LOCAL ONLY (no network access)" if local_files_only else "NETWORK ENABLED (may download models)"
            logInfo(f"        {mode_icon} Model loading mode: {mode_text}")

        for entry in results:
            label = entry['label']
            target = entry.get('path')
            optional = entry.get('optional', False)

            if entry.get('error'):
                icon = '❌'
                note = f"error: {entry['error']}"
            elif not target:
                icon = '⚠️' if optional else '❌'
                note = 'not set' + (' (optional)' if optional else '')
            elif entry['exists_after']:
                icon = '✅'
                if not entry['existed_before'] and entry.get('type') == 'dir':
                    note = 'created'
                else:
                    note = 'exists'
            else:
                icon = '⚠️' if optional else '❌'
                note = 'not present' + (' (optional)' if optional else '')

            # Display path relative to lib_root if possible, otherwise show full path
            target_display = target if target else '<unset>'
            if target and lib_root and target.startswith(lib_root):
                target_display = target[len(lib_root):].lstrip('/')
            
            logInfo(f"        {icon} {label}: {target_display} ({note})")

        if has_errors:
            logInfo("        ❌ Issues detected — update configuration before running pipeline")
        else:
            logInfo("        ✅ Pipeline config validation succeeded")

        return not has_errors


if __name__ == "__main__":
    import argparse
    import sys
    
    parser = argparse.ArgumentParser(description="SkiCycleRun Photo Processing Pipeline")
    parser.add_argument("--config", default="config/pipeline_config.json", help="Pipeline config file")
    parser.add_argument("--stages", nargs='+', help="Specific stages to run")
    parser.add_argument("--cache-only-geocode", action="store_true", help="Use geocoding cache only (no network calls)")
    parser.add_argument("--check-config", action="store_true", help="Validate config paths, report resolution details, then exit")
    parser.add_argument("--yes", action="store_true", help="Skip interactive confirmation prompt after config check")
    # Geocode sweep filters
    parser.add_argument("--sweep-path-contains", help="Only sweep entries whose path contains this substring")
    parser.add_argument("--sweep-limit", type=int, help="Limit number of entries processed in geocode sweep")
    parser.add_argument("--sweep-only-missing", action="store_true", help="Process only entries missing location/heading/POIs")
    parser.add_argument("--sweep-skip-poi", action="store_true", help="Skip POI fetching during sweep")
    parser.add_argument("--sweep-skip-heading", action="store_true", help="Skip EXIF heading extraction during sweep")
    parser.add_argument("--sweep-pulse-sec", type=int, default=5, help="Heartbeat interval in seconds for geocode sweep progress")
    parser.add_argument("--force-llm-reanalysis", action="store_true", help="Force LLM image analysis to re-run even if data already exists")
    parser.add_argument("--force-watermark", action="store_true", help="Force post-LoRA watermarking to re-process even if already watermarked")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output to terminal")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode - saves LLM prompts to llm_prompt_request.json")
    parser.add_argument("--debug-prompt", action="store_true", help="Save populated Stage 5 & 6 prompts to logs/ folder with image names")
    parser.add_argument("--force-clean", action="store_true", help="Force cleanup stage to delete folders even without export stage")
    
    args = parser.parse_args()
    
    # Store verbose flag globally for logger to use
    import utils.logger as logger_module
    logger_module.VERBOSE = args.verbose
    
    # Setup console logging only if not already configured (prevent duplicates)
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(logging.Formatter('%(message)s'))
        root_logger.addHandler(console_handler)
    root_logger.setLevel(logging.INFO)

    if not args.check_config:
        missing_envs = []
        if not os.getenv("SKICYCLERUN_LIB_ROOT"):
            missing_envs.append("SKICYCLERUN_LIB_ROOT")
        cache_env_present = any([
            os.getenv("HUGGINGFACE_CACHE_LIB"),
            os.getenv("HUGGINGFACE_CACHE"),
            os.getenv("HF_HOME"),
            os.getenv("TRANSFORMERS_CACHE"),
        ])
        if not cache_env_present:
            missing_envs.append("HUGGINGFACE_CACHE_LIB/HF_HOME")
        if missing_envs:
            logError(f"❌ Required environment variable(s) not set: {', '.join(missing_envs)}")
            logError("   Run: source ./env_setup.sh <images_root> [huggingface_cache] before executing the pipeline.")
            sys.exit(1)
        
        # Check HuggingFace authentication if lora_processing is requested
        stages_to_check = args.stages
        if stages_to_check and len(stages_to_check) == 1 and ',' in stages_to_check[0]:
            stages_to_check = [s.strip() for s in stages_to_check[0].split(',')]
        
        if stages_to_check and 'lora_processing' in stages_to_check:
            try:
                from huggingface_hub import HfFolder
                token = HfFolder.get_token()
                if not token:
                    logError("=" * 80)
                    logError("🔐 HUGGINGFACE AUTHENTICATION REQUIRED")
                    logError("=" * 80)
                    logError("❌ Not logged in to HuggingFace. LoRA processing requires authentication.")
                    logError("")
                    logError("To authenticate:")
                    logError("   1. Get your token from: https://huggingface.co/settings/tokens")
                    logError("   2. Run: hf auth login")
                    logError("   3. Paste your token when prompted")
                    logError("")
                    logError("To verify authentication:")
                    logError("   hf auth whoami")
                    logError("")
                    logError("=" * 80)
                    sys.exit(1)
                else:
                    # Silently authenticated - only show info if verbose
                    if args.verbose:
                        try:
                            from huggingface_hub import HfApi
                            api = HfApi()
                            user_info = api.whoami()
                            logInfo(f"✅ HuggingFace authenticated as: {user_info.get('name', 'Unknown')}")
                        except:
                            logInfo("✅ HuggingFace token found")
            except ImportError:
                logWarn("⚠️  Cannot verify HuggingFace authentication (huggingface_hub not installed)")
            except Exception as e:
                logWarn(f"⚠️  HuggingFace authentication check failed: {e}")
    
    runner = PipelineRunner(
        args.config,
        cache_only_geocode=args.cache_only_geocode,
        sweep_path_contains=args.sweep_path_contains,
        sweep_limit=args.sweep_limit,
        sweep_only_missing=args.sweep_only_missing,
        sweep_skip_poi=args.sweep_skip_poi,
        sweep_skip_heading=args.sweep_skip_heading,
        sweep_pulse_sec=args.sweep_pulse_sec,
        force_llm_reanalysis=args.force_llm_reanalysis,
        force_watermark=args.force_watermark,
        debug=args.debug,
        debug_prompt=args.debug_prompt,
    )
    
    # Handle comma-separated stages if provided as single argument
    stages_to_run = args.stages
    if stages_to_run and len(stages_to_run) == 1 and ',' in stages_to_run[0]:
        stages_to_run = [s.strip() for s in stages_to_run[0].split(',')]
    
    if args.check_config:
        logInfo("\n🧪 CONFIG CHECK MODE")
        if stages_to_run:
            logInfo(f"📋 Validating paths for stages: {', '.join(stages_to_run)}\n")
        else:
            logInfo("📋 Validating paths for all stages\n")
        ok = runner.check_config(stages_requested=stages_to_run)
        sys.exit(0 if ok else 1)

    ok = runner.check_config(stages_requested=stages_to_run)
    if not ok:
        logError("❌ Pipeline config validation failed. Aborting run.")
        sys.exit(1)

    if not args.yes:
        try:
            response = input("Proceed with pipeline run? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            response = ""
        if response not in ("y", "yes"):
            logWarn("🛑 Pipeline execution cancelled by user.")
            sys.exit(0)
    else:
        logInfo("✅ Proceeding without confirmation (--yes supplied).")

    # Setup file logging
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = log_dir / f"pipeline_{timestamp}.log"
    
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter('%(message)s'))
    logging.getLogger().addHandler(file_handler)
    logging.getLogger().setLevel(logging.INFO)
    
    # Log header with command info
    logInfo("=" * 80)
    logInfo(f"📝 Pipeline Run: {timestamp}")
    logInfo(f"📋 Command: pipeline.py --stages {' '.join(stages_to_run or [])} {'--yes' if args.yes else ''}")
    logInfo(f"📁 Log file: {log_file}")
    logInfo("=" * 80)

    runner.run_pipeline(stages_to_run)
