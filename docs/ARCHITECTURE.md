# Architecture: Export Stage Flow

**Command:** `python pipeline.py --stages export`

This document traces the complete code execution flow for the export stage, including the cleanup/preparation stage that precedes it.

---

## Complete Flow Tree

```
📦 pipeline.py
│
├─── main() - Entry Point
│    │
│    ├─── 1. Parse Command-Line Arguments
│    │    └─── argparse.ArgumentParser()
│    │         ├─── --stages export              # Stages to run
│    │         ├─── --config                     # Config file (default: config/pipeline_config.json)
│    │         ├─── --yes                        # Skip confirmation prompt
│    │         ├─── --check-config               # Validate paths only
│    │         ├─── --cache-only-geocode         # Geocoding cache mode
│    │         ├─── --sweep-* flags              # Geocode sweep filters
│    │         └─── --verbose                    # Enable verbose logging
│    │
│    ├─── 2. Environment Variable Validation (unless --check-config)
│    │    ├─── Check: SKICYCLERUN_LIB_ROOT
│    │    └─── Check: HUGGINGFACE_CACHE_LIB (or HF_HOME/HUGGINGFACE_CACHE/TRANSFORMERS_CACHE)
│    │         └─── Exit with error if missing
│    │
│    ├─── 3. Initialize PipelineRunner
│    │    │
│    │    └─── PipelineRunner.__init__()
│    │         ├─── Store config_path
│    │         ├─── Store optional filters (cache_only, sweep filters)
│    │         │
│    │         ├─── _load_config()
│    │         │    ├─── json.load("config/pipeline_config.json")
│    │         │    └─── utils.config_utils.resolve_config_placeholders()
│    │         │         ├─── Resolve ${ENV_VAR} → os.getenv()
│    │         │         └─── Resolve {path_key} → recursive substitution
│    │         │              └─── Example: {pipeline_base}/albums → /Volumes/.../pipeline/albums
│    │         │
│    │         ├─── Extract self.paths from config
│    │         ├─── Extract self.stages from config['pipeline']['stages']
│    │         │
│    │         └─── Initialize MasterStore
│    │              └─── core.master_store.MasterStore(master_catalog_path)
│    │                   └─── Loads/creates: {lib_root}/metadata/master.json
│    │
│    ├─── 4. Config Validation
│    │    │
│    │    └─── runner.check_config()
│    │         ├─── Path Validation Loop (path_specs[])
│    │         │    ├─── Library root: {lib_root}                      [CREATE DIR]
│    │         │    ├─── HuggingFace cache: {huggingface_cache}        [CREATE DIR]
│    │         │    ├─── Apple Photos export: albums/                  [CREATE DIR]
│    │         │    ├─── Raw input: albums/                            [CREATE DIR]
│    │         │    ├─── Preprocessed: scaled/                         [CREATE DIR]
│    │         │    ├─── Watermarked (pre-LoRA): watermarked_final/    [CREATE DIR]
│    │         │    ├─── LoRA processed: lora_processed/               [CREATE DIR]
│    │         │    ├─── Final albums: watermarked_final/              [CREATE DIR]
│    │         │    ├─── Archive: archive/                             [CREATE DIR]
│    │         │    ├─── Master catalog: metadata/master.json          [ENSURE PARENT]
│    │         │    ├─── Export script: scripts/osxPhotoExporter.scpt  [CHECK EXISTS]
│    │         │    ├─── Geocode cache: metadata/geocode_cache.json    [ENSURE PARENT]
│    │         │    ├─── LoRA input: scaled/                           [CREATE DIR]
│    │         │    ├─── LoRA output: lora_processed/                  [CREATE DIR]
│    │         │    └─── LoRA registry: config/lora_registry.json      [CHECK EXISTS]
│    │         │
│    │         ├─── Log Environment Variables
│    │         │    ├─── SKICYCLERUN_LIB_ROOT
│    │         │    ├─── HUGGINGFACE_CACHE_LIB
│    │         │    ├─── SKICYCLERUN_MODEL_LIB (legacy)
│    │         │    ├─── HF_HOME
│    │         │    ├─── HUGGINGFACE_CACHE
│    │         │    └─── TRANSFORMERS_CACHE
│    │         │
│    │         └─── Return: True (success) / False (has_errors)
│    │              └─── Exit if False
│    │
│    ├─── 5. User Confirmation Prompt
│    │    └─── input("Proceed with pipeline run? [y/N]: ")
│    │         ├─── Skip if --yes flag provided
│    │         └─── Exit if user responds != 'y'/'yes'
│    │
│    ├─── 6. Setup File Logging
│    │    ├─── Create logs/ directory (if not exists)
│    │    ├─── Generate timestamp: YYYYMMDD_HHMMSS
│    │    ├─── Create log file: logs/pipeline_{timestamp}.log
│    │    ├─── Add FileHandler to root logger
│    │    └─── Log header with command info
│    │
│    └─── 7. Run Pipeline
│         │
│         └─── runner.run_pipeline(['export'])
│              │
│              ├─── Log Pipeline Start
│              │    └─── "🚀 Starting SkiCycleRun Pipeline"
│              │         └─── "📋 Stages to run: export"
│              │
│              ├─── Check Ollama Availability (if needed by stages)
│              │    └─── Skipped for export stage (only needed for geocode_sweep, post_lora_watermarking)
│              │
│              ├─── Stage Map Definition
│              │    └─── stage_map = {
│              │         'export': run_export_stage,
│              │         'cleanup': lambda: run_cleanup_stage(stages),
│              │         'metadata_extraction': run_metadata_extraction_stage,
│              │         'llm_image_analysis': run_llm_image_analysis_stage,
│              │         'preprocessing': run_preprocessing_stage,
│              │         'lora_processing': run_lora_processing_stage,
│              │         'post_lora_watermarking': run_post_lora_watermarking_stage,
│              │         's3_deployment': run_s3_deployment_stage
│              │    }
│              │
│              └─── Stage Execution Loop
│                   │
│                   ├─── ═══════════════════════════════════════════════════════════
│                   │    🧹 STAGE 0: CLEANUP (IMPLICIT - runs before export)
│                   │    ═══════════════════════════════════════════════════════════
│                   │    │
│                   │    └─── run_cleanup_stage(stages_to_run=['export'])
│                   │         │
│                   │         ├─── Check: config['cleanup']['enabled'] == true
│                   │         │
│                   │         ├─── Determine Export Intent
│                   │         │    └─── will_export = 'export' in stages_to_run
│                   │         │         └─── True → Archive AND clean folders
│                   │         │              False → Archive only (preserve data)
│                   │         │
│                   │         ├─── Generate Timestamp
│                   │         │    └─── datetime.now().strftime('%Y%m%d_%H%M%S')
│                   │         │
│                   │         ├─── Archive Old Outputs (if config['cleanup']['archive_old_outputs'] == true)
│                   │         │    │
│                   │         │    ├─── Create Archive Base Directory
│                   │         │    │    └─── Path: {lib_root}/archive/
│                   │         │    │
│                   │         │    ├─── Identify Folders to Archive
│                   │         │    │    ├─── albums/         (if exists and non-empty)
│                   │         │    │    ├─── lora_processed/ (if exists and non-empty)
│                   │         │    │    └─── metadata/       (if exists and non-empty)
│                   │         │    │
│                   │         │    ├─── Create Temporary Archive Structure
│                   │         │    │    └─── tempfile.TemporaryDirectory()
│                   │         │    │         ├─── Create: temp_dir/pipeline_{timestamp}/
│                   │         │    │         └─── Copy folders to temp structure
│                   │         │    │              ├─── shutil.copytree(albums/ → temp/albums/)
│                   │         │    │              ├─── shutil.copytree(lora_processed/ → temp/lora_processed/)
│                   │         │    │              └─── shutil.copytree(metadata/ → temp/metadata/)
│                   │         │    │
│                   │         │    ├─── Create ZIP Archive
│                   │         │    │    └─── shutil.make_archive(
│                   │         │    │         source: temp_dir/pipeline_{timestamp}/
│                   │         │    │         format: 'zip'
│                   │         │    │         output: {lib_root}/archive/pipeline_{timestamp}.zip
│                   │         │    │         )
│                   │         │    │         └─── Log: Size in MB
│                   │         │    │
│                   │         │    └─── Clean Archived Folders (only if will_export == True)
│                   │         │         ├─── shutil.rmtree(albums/)
│                   │         │         ├─── shutil.rmtree(lora_processed/)
│                   │         │         ├─── shutil.rmtree(metadata/)
│                   │         │         └─── Recreate empty directories
│                   │         │              ├─── albums/.mkdir()
│                   │         │              ├─── lora_processed/.mkdir()
│                   │         │              └─── metadata/.mkdir()
│                   │         │
│                   │         └─── Log: "✅ Archive/cleanup complete - ready for new export"
│                   │
│                   └─── ═══════════════════════════════════════════════════════════
│                        📸 STAGE 1: EXPORT
│                        ═══════════════════════════════════════════════════════════
│                        │
│                        └─── run_export_stage()
│                             │
│                             ├─── Check: config['export']['enabled'] == true
│                             │    └─── Skip if false
│                             │
│                             ├─── Load Configuration Values
│                             │    ├─── script_path = config['export']['script_path']
│                             │    │    └─── Default: "scripts/osxPhotoExporter.scpt"
│                             │    │
│                             │    └─── export_path = paths['apple_photos_export']
│                             │         └─── Resolved: /Volumes/MySSD/skicyclerun.i2i/pipeline/albums
│                             │
│                             ├─── Execute AppleScript
│                             │    │
│                             │    └─── subprocess.run()
│                             │         ├─── Command: ['osascript', script_path, export_path]
│                             │         ├─── timeout: 3600 seconds (1 hour)
│                             │         ├─── capture_output: True
│                             │         ├─── text: True
│                             │         │
│                             │         └─── 📜 scripts/osxPhotoExporter.scpt
│                             │              │
│                             │              ├─── 1. Parse Arguments
│                             │              │    ├─── argv[0] = export_path (if provided)
│                             │              │    └─── Fallback Chain:
│                             │              │         ├─── $SKICYCLERUN_LIB_ROOT/pipeline/albums
│                             │              │         └─── /Volumes/MySSD/skicyclerun.i2i/pipeline/albums
│                             │              │
│                             │              ├─── 2. Verify Export Path Exists
│                             │              │    ├─── do shell script "test -d {export_path}"
│                             │              │    └─── If not found:
│                             │              │         └─── display dialog → choose folder
│                             │              │              └─── User can select alternate location
│                             │              │
│                             │              ├─── 3. Tell Application "Photos"
│                             │              │    │
│                             │              │    ├─── activate
│                             │              │    │    └─── Bring Photos.app to foreground
│                             │              │    │
│                             │              │    ├─── Get All Albums
│                             │              │    │    └─── albumList = name of albums
│                             │              │    │         └─── Returns: ["Vacation 2024", "Family", ...]
│                             │              │    │
│                             │              │    ├─── Check Album Count
│                             │              │    │    └─── if count == 0:
│                             │              │    │         └─── display dialog "No albums found"
│                             │              │    │              └─── Exit
│                             │              │    │
│                             │              │    ├─── Present Album Selection Dialog
│                             │              │    │    └─── choose from list albumList
│                             │              │    │         ├─── with prompt: "Select albums to export:"
│                             │              │    │         ├─── with multiple selections allowed
│                             │              │    │         └─── Returns: selectedAlbums[] or false (cancelled)
│                             │              │    │
│                             │              │    ├─── Handle Cancellation
│                             │              │    │    └─── if selectedAlbums == false:
│                             │              │    │         └─── log "Export cancelled by user"
│                             │              │    │              └─── Exit
│                             │              │    │
│                             │              │    └─── Export Loop (for each selected album)
│                             │              │         │
│                             │              │         ├─── Get Album Object
│                             │              │         │    └─── currentAlbum = first album whose name is albumName
│                             │              │         │
│                             │              │         ├─── Get Photo Count
│                             │              │         │    └─── photoCount = count of media items of currentAlbum
│                             │              │         │
│                             │              │         ├─── Sanitize Album Name
│                             │              │         │    └─── sanitizeFilename(albumName)
│                             │              │         │         ├─── Remove invalid chars: / : \ * ? " < > |
│                             │              │         │         └─── Replace with: _
│                             │              │         │              └─── Example: "Vacation/2024" → "Vacation_2024"
│                             │              │         │
│                             │              │         ├─── Create Album Folder
│                             │              │         │    └─── albumFolder = {export_path}/{sanitizedName}
│                             │              │         │         └─── makeFolder(albumFolder)
│                             │              │         │              └─── do shell script "mkdir -p {albumFolder}"
│                             │              │         │
│                             │              │         ├─── Export Photos
│                             │              │         │    └─── with timeout of 600 seconds (10 min per album)
│                             │              │         │         └─── export (get media items of currentAlbum)
│                             │              │         │              to: POSIX file albumFolder as alias
│                             │              │         │              ├─── with metadata    # Preserve all EXIF/IPTC
│                             │              │         │              ├─── with GPS         # Include GPS coordinates
│                             │              │         │              └─── without using originals  # Export as JPEG (not HEIC)
│                             │              │         │
│                             │              │         ├─── Error Handling
│                             │              │         │    └─── on error: log "✗ ERROR exporting album"
│                             │              │         │
│                             │              │         └─── Log Progress
│                             │              │              └─── "✓ Completed: {albumName} ({photoCount} photos exported)"
│                             │              │
│                             │              └─── 4. Display Completion Dialog
│                             │                   └─── display dialog "Export complete! N albums exported to: {path}"
│                             │
│                             ├─── Check Subprocess Return Code
│                             │    ├─── returncode == 0: Success
│                             │    │    └─── utils.logger.logInfo("✅ Export complete")
│                             │    │         └─── Log stdout from AppleScript
│                             │    │
│                             │    └─── returncode != 0: Failure
│                             │         └─── utils.logger.logError("❌ Export failed")
│                             │              └─── Log stderr from AppleScript
│                             │
│                             └─── Exception Handling
│                                  ├─── subprocess.TimeoutExpired (1 hour timeout)
│                                  └─── General Exception
│                                       └─── utils.logger.logError("❌ Export error: {e}")
```

---

## Files Touched During Export Stage

### Core Python Modules

| File                                               | Purpose           | Operations                                   |
| -------------------------------------------------- | ----------------- | -------------------------------------------- |
| **[pipeline.py](pipeline.py)**                     | Main orchestrator | Entry point, stage routing, logging setup    |
| **[utils/config_utils.py](utils/config_utils.py)** | Config resolution | Resolve ${ENV} and {path} placeholders       |
| **[utils/logger.py](utils/logger.py)**             | Logging functions | logInfo(), logError(), logWarn()             |
| **[core/master_store.py](core/master_store.py)**   | Metadata store    | Initialized but not used during export stage |

### Configuration Files

| File                                                           | Purpose           | Content                              |
| -------------------------------------------------------------- | ----------------- | ------------------------------------ |
| **[config/pipeline_config.json](config/pipeline_config.json)** | Pipeline settings | Paths, stage config, export settings |

### Scripts

| File                                                               | Purpose           | Language    |
| ------------------------------------------------------------------ | ----------------- | ----------- |
| **[scripts/osxPhotoExporter.scpt](scripts/osxPhotoExporter.scpt)** | Photos.app export | AppleScript |

### Output Artifacts

| Path                                          | Contents                                | Created By         |
| --------------------------------------------- | --------------------------------------- | ------------------ |
| `{lib_root}/archive/pipeline_{timestamp}.zip` | Archived albums, metadata, lora outputs | Cleanup stage      |
| `{lib_root}/pipeline/albums/[AlbumName]/`     | Exported JPEG files with EXIF/GPS       | AppleScript export |
| `logs/pipeline_{timestamp}.log`               | Execution log with timestamps           | Python logging     |

---

## Data Flow

### Stage 0: Cleanup (Pre-Export)

```
┌──────────────────────────────────────────────────────────────┐
│  INPUT: Existing pipeline directories                         │
│  - albums/ (old exports)                                      │
│  - lora_processed/ (old processed images)                     │
│  - metadata/ (old master.json)                                │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  PROCESS: Archive & Clean                                     │
│  1. Create temporary directory structure                      │
│  2. Copy folders to temp location                             │
│  3. Create ZIP: archive/pipeline_{timestamp}.zip              │
│  4. Delete original folders (only if 'export' in stages)      │
│  5. Recreate empty directories                                │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  OUTPUT: Clean slate for new export                           │
│  ✅ albums/ (empty, ready for new export)                     │
│  ✅ lora_processed/ (empty)                                   │
│  ✅ metadata/ (empty, master.json will be regenerated)        │
│  ✅ archive/pipeline_{timestamp}.zip (backup of old data)     │
└──────────────────────────────────────────────────────────────┘
```

### Stage 1: Export

```
┌──────────────────────────────────────────────────────────────┐
│  INPUT: Apple Photos Library                                  │
│  - User-selected albums via GUI dialog                        │
│  - Photos with EXIF metadata (GPS, date, camera info)        │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  PROCESS: AppleScript Export                                  │
│  1. Prompt user to select albums                              │
│  2. For each album:                                           │
│     a. Sanitize album name (remove / : \ * ? " < > |)        │
│     b. Create folder: albums/{AlbumName}/                     │
│     c. Export photos as JPEG with metadata + GPS              │
│  3. Report completion status                                  │
└──────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────┐
│  OUTPUT: Organized album folders                              │
│  albums/                                                       │
│  ├── Vacation_2024/                                           │
│  │   ├── IMG_1001.jpg  (with EXIF + GPS)                     │
│  │   ├── IMG_1002.jpg                                         │
│  │   └── IMG_1003.jpg                                         │
│  └── Family_Photos/                                           │
│      ├── IMG_2001.jpg                                         │
│      └── IMG_2002.jpg                                         │
│                                                                │
│  logs/pipeline_{timestamp}.log (execution log)                │
└──────────────────────────────────────────────────────────────┘
```

---

## Key Design Patterns

### 1. Stage Immutability

- **Cleanup stage** never modifies `albums/` if export isn't running
- **Export stage** only writes to `albums/`, never modifies other directories
- Each stage has clearly defined input/output boundaries

### 2. Atomic Operations

- Archive creation uses temporary directory before final ZIP
- AppleScript exports per album with individual timeout (10 min)
- Folders only deleted AFTER successful archive creation

### 3. Graceful Degradation

- Missing export path → prompt user to select folder
- No albums in Photos library → display error and exit
- User cancels album selection → log cancellation and exit cleanly

### 4. Idempotency

- Cleanup can run multiple times (creates new timestamped archives)
- Export to existing folders appends/overwrites (Photos.app behavior)
- No stage should fail if run twice consecutively

---

## Current Architecture Issues

### 🔴 Critical Issues

1. **No Export Cataloging**
   - Exported files are NOT recorded in `master.json`
   - Downstream stages must rediscover files via filesystem scan
   - No tracking of export timestamp or source album

2. **Heavy Initialization for Simple Export**
   - Full config load and validation even for single stage
   - MasterStore initialized but unused
   - All paths validated (LoRA, watermark, S3) when only `albums/` needed

3. **No Progress Visibility**
   - AppleScript runs in subprocess with no streaming output
   - No per-photo progress, only per-album completion log
   - User sees "waiting..." for up to 10 minutes per album

### ⚠️ Medium Issues

4. **Cleanup Logic Coupled to Export**
   - `will_export` flag couples cleanup behavior to pipeline intent
   - Can't run cleanup independently to archive without cleaning
   - Confusing behavior: `--stages cleanup` alone doesn't clean!

5. **Error Handling Gaps**
   - Partial album export failures not tracked
   - If AppleScript times out, unclear which albums succeeded
   - No retry mechanism for failed albums

6. **Config Validation Overkill**
   - Checks LoRA registry path even for export-only run
   - Creates all pipeline directories regardless of stages requested
   - Validates S3 paths when only exporting locally

### ✅ Strengths

- Clean separation: Python orchestration, AppleScript for Photos.app
- User-friendly album selection dialog
- Proper EXIF/GPS preservation in export
- Archive creates timestamped backups before cleaning

---

## Recommended Improvements

### Phase 1: Quick Wins (Implement Now)

1. **Add Export Cataloging**

   ```python
   # In run_export_stage() after successful export:
   if result.returncode == 0 and self.master_store:
       self._catalog_exported_files()
   ```

2. **Stage-Specific Validation**

   ```python
   def check_config(self, stages_requested=None):
       if stages_requested == ['export']:
           # Only validate: lib_root, albums/, export script
           # Skip: LoRA paths, S3 config, registry check
   ```

3. **Decouple Cleanup from Export**
   ```python
   def run_cleanup_stage(self, force_clean=False):
       # New flag: force_clean overrides will_export logic
       # Allows: --stages cleanup --force-clean
   ```

### Phase 2: Architecture Refactor (Future)

4. **Lazy Stage Initialization**
   - Don't initialize MasterStore until first used
   - Load config sections on-demand per stage
   - Defer heavy imports (torch, diffusers) until LoRA stage

5. **Streaming Export Progress**
   - Modify AppleScript to emit progress logs
   - Python captures and displays real-time updates
   - Example: "PROGRESS: album_2_of_5 | photo_15_of_42"

6. **Standalone Export Module**
   ```python
   # New: core/photo_exporter.py
   class PhotoExporter:
       def export_albums(self, selected=None) -> ExportResult
       def catalog_exports(self, master_store) -> int
       def verify_exports(self) -> List[Issue]
   ```

---

## Testing Checklist

### Export Stage

- [ ] Fresh export to empty `albums/` directory
- [ ] Export with existing files (overwrites)
- [ ] User cancels album selection
- [ ] AppleScript timeout (>1 hour total export time)
- [ ] Export path doesn't exist → user selects folder
- [ ] No albums in Photos library
- [ ] Export with albums containing special chars in name

### Cleanup Stage

- [ ] Cleanup with empty directories (no archive created)
- [ ] Cleanup with export in stages → folders deleted
- [ ] Cleanup without export in stages → folders preserved
- [ ] Multiple cleanups create multiple timestamped archives
- [ ] Archive ZIP integrity (can extract and verify contents)
- [ ] Disk full during archive creation

---

## Environment Dependencies

### Required Tools

- Python 3.13+
- macOS with Apple Photos.app
- osascript (AppleScript interpreter)

### Required Permissions

- Terminal.app: Full Disk Access (System Settings → Privacy & Security)
- Photos.app: Must be authorized to access library

### Required Environment Variables

- `SKICYCLERUN_LIB_ROOT` - Base directory for pipeline data
- `HUGGINGFACE_CACHE_LIB` (or `HF_HOME`) - Model cache location

---

**Document Version:** 1.0  
**Last Updated:** December 6, 2025  
**Pipeline Version:** 1.0.0
