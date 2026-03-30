"""
Pipeline Task Runner
Orchestrates the full photo processing pipeline from Apple Photos export to LoRA processing
"""
import json
import os
import time
import re
import subprocess
import logging
import importlib
import sys
from pathlib import Path
from datetime import datetime
from utils.config_utils import resolve_config_placeholders
from utils.time_utils import utc_now_iso_z
from typing import Dict, List
from core.geo_extractor import GeoExtractor
from core.image_preprocessor import ImagePreprocessor
from core.master_store import MasterStore
from utils.logger import logInfo, logError, logWarn

# Auto-load .env from project root so API keys don't need manual export each session
_env_file = Path(__file__).parent / '.env'
if _env_file.exists():
    with open(_env_file) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _, _v = _line.partition('=')
                os.environ.setdefault(_k.strip(), _v.strip())

# Transformers deprecates TRANSFORMERS_CACHE in favor of HF_HOME.
# Keep backwards compatibility with old shells while suppressing the warning.
if os.getenv("TRANSFORMERS_CACHE"):
    if not os.getenv("HF_HOME"):
        os.environ["HF_HOME"] = os.environ["TRANSFORMERS_CACHE"]
    del os.environ["TRANSFORMERS_CACHE"]

# Setup file logging - will be initialized in main() with stage info


class TeeStream:
    """Write output to terminal and a log file simultaneously."""

    def __init__(self, stream, log_file):
        self._stream = stream
        self._log_file = log_file

    def write(self, data):
        if not data:
            return 0
        self._stream.write(data)
        self._log_file.write(data)
        return len(data)

    def flush(self):
        self._stream.flush()
        self._log_file.flush()


def resolve_log_file_path(resolved_config: Dict, timestamp: str) -> Path:
    """Resolve the configured log path and substitute the run timestamp."""
    logging_cfg = (resolved_config or {}).get('logging', {}) or {}
    configured = str(logging_cfg.get('file', 'logs/pipeline_{timestamp}.log'))
    rendered = configured.replace('{timestamp}', timestamp)
    log_path = Path(rendered)

    # Keep relative paths anchored to project root.
    if not log_path.is_absolute():
        log_path = Path(__file__).parent / log_path

    return log_path


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
        self.force_watermark = force_watermark
        self.debug = debug
        # LLM image analysis stage removed from active pipeline flow.
        
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

    def _load_geocode_cache(self) -> Dict:
        """Load geocode cache used for POI and per-coordinate photo grouping."""
        metadata_dir = Path(self.paths.get('metadata_dir', ''))
        cache_path = metadata_dir / 'geocode_cache.json'
        if not cache_path.exists():
            return {}
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logWarn(f"⚠️  Failed to load geocode cache: {e}")
            return {}

    def _state_short(self, state: str, country_code: str) -> str:
        """Abbreviate common provinces/states for compact watermark lines."""
        if not state:
            return ''
        if (country_code or '').upper() == 'CA':
            ca_map = {
                'Alberta': 'AB',
                'British Columbia': 'BC',
                'Manitoba': 'MB',
                'New Brunswick': 'NB',
                'Newfoundland and Labrador': 'NL',
                'Northwest Territories': 'NT',
                'Nova Scotia': 'NS',
                'Nunavut': 'NU',
                'Ontario': 'ON',
                'Prince Edward Island': 'PE',
                'Quebec': 'QC',
                'Saskatchewan': 'SK',
                'Yukon': 'YT',
            }
            return ca_map.get(state, state)
        return state

    def _get_source_gps(self, source_metadata: Dict) -> tuple[float | None, float | None]:
        """Return source GPS coordinates from master.json metadata when present."""
        gps = source_metadata.get('gps', {}) or {}
        lat = gps.get('lat')
        lon = gps.get('lon')
        if lat is None or lon is None:
            return None, None
        try:
            return float(lat), float(lon)
        except (TypeError, ValueError):
            return None, None
    
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
        failed_count = 0
        stage_start = time.perf_counter()
        batch_elapsed_sum = 0.0
        batch_count = 0

        def _fmt_elapsed(seconds: float) -> str:
            total = max(0, int(round(seconds)))
            h, rem = divmod(total, 3600)
            m, s = divmod(rem, 60)
            if h > 0:
                return f"{h:02d}:{m:02d}:{s:02d}"
            return f"{m:02d}:{s:02d}"
        
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
            image_start = time.perf_counter()
            image_status = "ok"
            
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
                    if entry and "llm_image_analysis" in entry:
                        del entry["llm_image_analysis"]
                        pipeline_node = entry.get('pipeline', {})
                        stages = pipeline_node.get('stages', [])
                        if 'llm_image_analysis' in stages:
                            pipeline_node['stages'] = [s for s in stages if s != 'llm_image_analysis']
                        timestamps = pipeline_node.get('timestamps', {})
                        if 'llm_image_analysis' in timestamps:
                            del timestamps['llm_image_analysis']
                    
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
                
            except Exception as e:
                image_status = "failed"
                failed_count += 1
                logWarn(f"⚠️  Failed to extract metadata from {image_path.name}: {e}")

            image_elapsed = time.perf_counter() - image_start
            batch_elapsed_sum += image_elapsed
            batch_count += 1
            total_elapsed_so_far = time.perf_counter() - stage_start
            print(f"   ⏱️  Image time: {_fmt_elapsed(image_elapsed)} ({image_elapsed:.2f}s, {image_status})")
            print(f"   ⏱️  Total elapsed so far: {_fmt_elapsed(total_elapsed_so_far)}")

            if batch_count == 10:
                avg_batch = batch_elapsed_sum / batch_count
                print("\n" + "─" * 60)
                logInfo(
                    f"  ⏱️  Last 10 images: total {_fmt_elapsed(batch_elapsed_sum)} ({batch_elapsed_sum:.2f}s), "
                    f"avg {avg_batch:.2f}s/image"
                )
                logInfo(
                    f"  📊 Progress: processed={new_count + failed_count}, success={new_count}, "
                    f"failed={failed_count}, skipped={skipped_count}"
                )
                print("─" * 60 + "\n")
                batch_elapsed_sum = 0.0
                batch_count = 0
        
        stage_elapsed = time.perf_counter() - stage_start
        print("\n" + "─" * 60)
        logInfo(
            f"✅ Metadata extraction complete - {new_count} new, {failed_count} failed, {skipped_count} skipped"
        )
        logInfo(f"⏱️  Stage 2 total elapsed: {_fmt_elapsed(stage_elapsed)} ({stage_elapsed:.2f}s)")
        if (new_count + failed_count) > 0:
            avg_all = stage_elapsed / (new_count + failed_count)
            logInfo(f"⏱️  Average time per processed image: {avg_all:.2f}s")
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
        """Stage 5: Pre-LoRA watermarking (optional)."""
        wm_cfg = self.config.get('watermark', {})
        if not wm_cfg.get('enabled', False):
            logInfo("⏭️  Watermarking disabled, skipping...")
            return

        if not wm_cfg.get('apply_before_lora', True):
            logInfo("⏭️  Pre-LoRA watermarking disabled via apply_before_lora=false")
            return

        # Kept for compatibility with stage map; primary watermarking happens post-LoRA.
        logInfo("ℹ️  Pre-LoRA watermarking compatibility stage retained but not used in current flow.")

    def run_llm_image_analysis_stage(self):
        """Deprecated: LLM stage removed from active pipeline."""
        logWarn("⏭️  llm_image_analysis stage has been removed from active pipeline flow.")
        logWarn("   Watermark content now comes from POI + geolocation templates only.")
    
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
            
            # Call LoRA transformer with batch processing.
            # NoLoRA pass-through is handled inside core/lora_transformer.py.
            cmd = [
                sys.executable,
                'core/lora_transformer.py',
                '--lora', lora_name,
                '--batch',
                '--input-folder', input_folder,
                '--output-folder', output_folder
            ]

            # Force subprocess logs into the same per-run pipeline log.
            run_log_file = os.getenv('SKICYCLERUN_RUN_LOG_FILE')
            if run_log_file:
                cmd.extend(['--log-file', run_log_file])
            
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
        
        from core.watermark_applicator import WatermarkApplicator
        from core.copyright_embedder import CopyrightEmbedder
        from core.poi_watermark_engine import build_watermark_from_cached_context
        
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
        
        watermark_app = WatermarkApplicator(temp_config)
        
        copyright_enabled = self.config.get('copyright', {}).get('enabled', False)
        copyright_embedder = CopyrightEmbedder(temp_config) if copyright_enabled else None
        
        # Scan lora_processed folder for actual LoRA images
        processed = 0
        watermarked = 0
        skipped = 0
        skipped_no_metadata = 0
        failed = 0
        
        lora_images = find_images_in_directory(lora_folder)
        geocode_cache = self._load_geocode_cache()

        if not geocode_cache:
            logError("❌ geocode_cache.json is missing or empty.")
            logError("   Run metadata extraction first to build GPS/POI context:")
            logError("   python pipeline.py --stages metadata_extraction")
            logError("   Then run watermarking:")
            logError("   python pipeline.py --stages post_lora_watermarking")
            return
        
        logInfo(f"📊 Found {len(lora_images)} LoRA-processed images")
        
        # Build stem → (path_str, entry) index for O(1) lookup.
        # Index by path stem AND by the stored file_name field, so entries are found
        # even when the on-disk path has changed (e.g. after archive/restore).
        stem_index: dict = {}
        for path_str, entry in self.master_store.list_paths().items():
            for candidate in (Path(path_str).stem, Path(entry.get('file_name', '')).stem):
                if candidate and candidate not in stem_index:
                    stem_index[candidate] = (path_str, entry)
        
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
            
            # Look up source metadata via the pre-built stem index
            source_metadata = None
            source_path = None
            if original_stem in stem_index:
                source_path, source_metadata = stem_index[original_stem]
            
            if not source_metadata:
                # Do not watermark files that are not represented in master.json.
                # This keeps existing folders untouched and avoids generating output
                # for images that were never cataloged/metadata-extracted.
                logWarn(f"⏭️  Skipping {lora_path.name}: no source metadata in master.json (stem: {original_stem})")
                skipped_no_metadata += 1
                continue

            # Clean up legacy literal keys like "lora_watermarks.Origami".
            # New schema stores one source-level watermark section plus
            # per-style output records under watermarked_outputs.
            legacy_watermark_keys = [k for k in list(source_metadata.keys()) if k.startswith('lora_watermarks.')]
            for legacy_key in legacy_watermark_keys:
                source_metadata.pop(legacy_key, None)

            # Require metadata_extraction to have run for this source image.
            source_stages = set((source_metadata.get('pipeline') or {}).get('stages') or [])
            if 'metadata_extraction' not in source_stages:
                logWarn(f"⏭️  Skipping {lora_path.name}: source image missing metadata_extraction in master.json")
                skipped_no_metadata += 1
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
                # Load LoRA generation metadata from master.json.
                # lora_transformer.py saves it as a flat dot-key: "lora_generations.{style}"
                # We also check the nested form for forward compat.
                lora_generation_params = (
                    source_metadata.get(f'lora_generations.{style_name}') or
                    source_metadata.get('lora_generations', {}).get(style_name) or
                    {}
                )
                
                if lora_generation_params:
                    logInfo(f"✓ Loaded LoRA metadata: seed={lora_generation_params.get('seed')}, steps={lora_generation_params.get('num_inference_steps')}")
                
                source_lat, source_lon = self._get_source_gps(source_metadata)
                if source_lat is None or source_lon is None:
                    raise RuntimeError(
                        f"Missing source GPS metadata for {lora_path.name}. "
                        "Run CLI with --stages metadata_extraction before post_lora_watermarking."
                    )

                cached_geo_entry = {}
                cache_key = f"{source_lat:.6f},{source_lon:.6f}"
                cached_geo_entry = geocode_cache.get(cache_key, {}) or {}

                if not cached_geo_entry:
                    source_photo_name = source_metadata.get('file_name')
                    if source_photo_name:
                        for _, cache_entry in geocode_cache.items():
                            photos = cache_entry.get('photos', []) or []
                            if source_photo_name in photos:
                                cached_geo_entry = cache_entry or {}
                                break

                if not cached_geo_entry:
                    raise RuntimeError(
                        f"Missing geocode_cache entry for {lora_path.name} ({cache_key}). "
                        "Run CLI with --stages metadata_extraction before post_lora_watermarking."
                    )

                if 'nearby_pois' not in cached_geo_entry:
                    raise RuntimeError(
                        f"Incomplete geocode_cache entry for {lora_path.name} ({cache_key}): nearby_pois missing. "
                        "Run CLI with --stages metadata_extraction before post_lora_watermarking."
                    )

                watermark_result = build_watermark_from_cached_context(
                    lat=source_lat,
                    lon=source_lon,
                    location=source_metadata.get('location') or {},
                    cached_geo=cached_geo_entry,
                    bilingual_output=bool(watermark_config.get('bilingual_output', True)),
                )

                line1_text = watermark_result.get('line1', '')
                line2_text = watermark_result.get('line2', '')
                line1_debug = []
                if watermark_result.get('known_hint'):
                    line1_debug.append(
                        f"   🧭 Hint match: {watermark_result['known_hint'].get('line1')} "
                        f"({watermark_result['known_hint'].get('distance_m', 0):.0f}m)"
                    )
                if watermark_result.get('here_place'):
                    here_place = watermark_result['here_place']
                    line1_debug.append(
                        f"   📍 Here: {here_place.get('name')} [{here_place.get('type')}]"
                    )
                nearby_pois = watermark_result.get('nearby_pois') or []
                if nearby_pois:
                    line1_debug.append('   ✨ Nearby context:')
                    for poi in nearby_pois[:5]:
                        direction = poi.get('bearing_cardinal') or '?'
                        line1_debug.append(
                            f"      - {poi.get('name')} [{poi.get('type')}] "
                            f"({float(poi.get('distance_m') or 0):.0f}m {direction})"
                        )

                # Optional seed logging only (keep watermark lines clean).
                seed_value = lora_generation_params.get('seed')
                
                # LOG TO TERMINAL
                print(f"\n💧 Watermarking: {lora_path.name}")
                for debug_line in line1_debug:
                    print(debug_line)
                print(f"   🏷️  LINE 1: {line1_text}")
                print(f"   🏷️  LINE 2: {line2_text}")
                print(f"   ✅ RESULT: {line1_text} | {line2_text}")
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
                applied_at = utc_now_iso_z()
                watermark_section = {
                    'line1': line1_text,
                    'line2': line2_text,
                    'watermark_sources': {
                        'line1': 'core.poi_watermark_engine.build_two_line_watermark',
                        'line2': 'core.poi_watermark_engine.format_line2 + copyright formatter'
                    },
                    'layout': watermark_config.get('layout', 'two_line'),
                    'font_size': font_cfg.get('size'),
                    'position': watermark_config.get('position'),
                    'updated_at': applied_at
                }
                watermarked_output_record = {
                    'style': style_name,
                    'lora_path': str(lora_path),
                    'output_path': str(output_file),
                    'applied_at': applied_at
                }
                
                # Update the source entry with watermark info
                if source_path:
                    self.master_store.update_section(source_path, 'watermark', watermark_section, stage='post_lora_watermarking')
                    self.master_store.update_section(
                        source_path,
                        'watermarked_outputs',
                        {style_name: watermarked_output_record},
                        stage='post_lora_watermarking'
                    )
                
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
        logInfo(f"   Skipped: {skipped_no_metadata} (missing metadata in master.json)")
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

        wm_cfg = self.config.get('watermark', {}) or {}
        bilingual_output = bool(wm_cfg.get('bilingual_output', True))
        
        logInfo(f"🚀 Starting SkiCycleRun Pipeline")
        logInfo(f"📋 Stages to run: {', '.join(stages)}")
        logInfo(f"🈯 Watermark bilingual output: {'ON' if bilingual_output else 'OFF'}")

        if 'post_lora_watermarking' in stages and 'metadata_extraction' not in stages:
            logWarn("⚠️  post_lora_watermarking requested without metadata_extraction in this run.")
            logWarn("   This stage requires GPS + geocode_cache context prepared by metadata_extraction.")
            logWarn("   Recommended first run: python pipeline.py --stages metadata_extraction")
            logWarn("   Then run: python pipeline.py --stages post_lora_watermarking")
        
        # Get force_clean flag from args if available
        force_clean = getattr(self, '_force_clean', False)
        
        stage_map = {
            'export': self.run_export_stage,
            'cleanup': lambda: self.run_cleanup_stage(stages, force_clean=force_clean),
            'metadata_extraction': self.run_metadata_extraction_stage,
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
            'export',
            'cleanup',
            'metadata_extraction',
            'preprocessing',
            'watermarking',
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
                'export': '   Export photos from Apple Photos',
                'metadata_extraction': '   Extract EXIF metadata and GPS coordinates from exported images',
                'preprocessing': '   Resize and optimize images for LoRA processing',
                'watermarking': '   Run compatibility pre-LoRA watermark stage',
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

        wm_cfg = self.config.get('watermark', {}) or {}
        bilingual_output = bool(wm_cfg.get('bilingual_output', True))
        logInfo(f"        🈯 Watermark bilingual output: {'ON' if bilingual_output else 'OFF'}")

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

    stages_help = (
        "Specific stages to run. Valid stages:\n"
        "  cleanup                Remove existing pipeline output folders\n"
        "  export                 Export photos from Apple Photos\n"
        "  metadata_extraction    Extract EXIF/GPS + geocode + POI cache\n"
        "  preprocessing          Resize and optimize source images\n"
        "  watermarking           Pre-LoRA watermark stage (compatibility)\n"
        "  lora_processing        Generate style variants with LoRA\n"
        "  post_lora_watermarking Build/apply final LINE1/LINE2 watermarks\n"
        "  s3_deployment          Upload final outputs to AWS S3"
    )
    
    parser = argparse.ArgumentParser(
        description="SkiCycleRun Photo Processing Pipeline",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--config", default="config/pipeline_config.json", help="Pipeline config file")
    parser.add_argument("-stages", "--stages", nargs='+', help=stages_help)
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

    # Set up the log file immediately so all output — env-var errors, config
    # failures, and user cancellations — is captured from the very start of
    # the run.  Try the config-resolved path first; fall back to the project-
    # local logs/ directory if that path is inaccessible (e.g. SSD unmounted).
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    try:
        with open(args.config, 'r', encoding='utf-8') as _cf:
            _early_cfg = resolve_config_placeholders(json.load(_cf))
    except Exception:
        _early_cfg = None
    log_file = resolve_log_file_path(_early_cfg, timestamp)
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        _file_handler = logging.FileHandler(log_file, encoding='utf-8')
    except OSError:
        # Configured log path is not writable (e.g. external drive not mounted);
        # fall back to the project-local logs/ directory.
        log_file = resolve_log_file_path(None, timestamp)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        _file_handler = logging.FileHandler(log_file, encoding='utf-8')
    _file_handler.setLevel(logging.INFO)
    _file_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s', '%Y-%m-%d %H:%M:%S'
    ))
    root_logger.addHandler(_file_handler)
    # Share this run log path with child subprocesses (e.g., LoRA stage).
    os.environ['SKICYCLERUN_RUN_LOG_FILE'] = str(log_file)
    logInfo("=" * 80)
    logInfo(f"📝 Pipeline Run: {timestamp}")
    logInfo(f"📋 Command: pipeline.py {' '.join(sys.argv[1:])}")
    logInfo(f"📁 Log file: {log_file}")
    logInfo("=" * 80)

    if not args.check_config:
        # Accept config/pipeline_config.json path values as fallback when env vars
        # are not exported in the current shell session.
        try:
            with open(args.config, 'r', encoding='utf-8') as _cf:
                _raw_cfg = json.load(_cf)
            _resolved_cfg = resolve_config_placeholders(_raw_cfg)
            _cfg_paths = _resolved_cfg.get('paths', {}) if isinstance(_resolved_cfg, dict) else {}

            _cfg_lib_root = _cfg_paths.get('lib_root')
            _cfg_hf_cache = _cfg_paths.get('huggingface_cache')

            if _cfg_lib_root and not os.getenv('SKICYCLERUN_LIB_ROOT'):
                os.environ['SKICYCLERUN_LIB_ROOT'] = str(_cfg_lib_root)

            if _cfg_hf_cache:
                os.environ.setdefault('HUGGINGFACE_CACHE_LIB', str(_cfg_hf_cache))
                os.environ.setdefault('HF_HOME', str(_cfg_hf_cache))
                os.environ.setdefault('HUGGINGFACE_CACHE', str(_cfg_hf_cache))
        except Exception as _cfg_err:
            logWarn(f"⚠️  Could not pre-resolve config fallbacks from {args.config}: {_cfg_err}")

        missing_envs = []
        if not os.getenv("SKICYCLERUN_LIB_ROOT"):
            missing_envs.append("SKICYCLERUN_LIB_ROOT")
        cache_env_present = any([
            os.getenv("HUGGINGFACE_CACHE_LIB"),
            os.getenv("HUGGINGFACE_CACHE"),
            os.getenv("HF_HOME"),
        ])
        if not cache_env_present:
            missing_envs.append("HUGGINGFACE_CACHE_LIB/HF_HOME")
        if missing_envs:
            logError(f"❌ Required environment variable(s) not set: {', '.join(missing_envs)}")
            logError("   Run: ./run_SetupEnv.sh --profile performance/macmini-fast-20260326.txt before executing the pipeline.")
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

    runner.run_pipeline(stages_to_run)
