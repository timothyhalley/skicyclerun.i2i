# Pipeline Restructuring Summary

## Overview

The pipeline has been restructured to use a clear numbered-stage directory layout that makes it much easier to track output and debug issues.

## New Directory Structure

```plaintext
$SKICYCLERUN_LIB_ROOT/
└── pipeline/
    ├── archive/              # Stage 0: Archived work
    │   ├── albums/           # Old albums
    │   └── metadata/         # Versioned metadata (master_v{N}_{timestamp}.json)
    │
    ├── albums/               # Stage 1: NEW Apple Photos exports
    ├── metadata/             # Stage 2: Extracted metadata
    ├── scaled/               # Stage 3: Preprocessed images
    ├── lora_processed/       # Stage 4: LoRA-styled images
    └── watermarked_final/    # Stage 5: Final watermarked images → S3
```

## Key Changes

### 1. Configuration (`config/pipeline_config.json`)

**Updated paths**:

```json
{
  "paths": {
    "pipeline_base": "{lib_root}/pipeline",
    "archive_albums": "{pipeline_base}/archive/albums",
    "archive_metadata": "{pipeline_base}/archive/metadata",
    "apple_photos_export": "{pipeline_base}/albums",
    "metadata_dir": "{pipeline_base}/metadata",
    "preprocessed": "{pipeline_base}/scaled",
    "lora_processed": "{pipeline_base}/lora_processed",
    "watermarked_final": "{pipeline_base}/watermarked_final",
    "master_catalog": "{metadata_dir}/master.json"
  }
}
```

### 2. Apple Photos Export Script (`scripts/osxPhotoExporter.scpt`)

**Now exports to**: `$SKICYCLERUN_LIB_ROOT/pipeline/albums/`

**Default path changed from**:

- Old: `images/raw`
- New: `pipeline/albums`

### 3. Documentation

**New files**:

- `PIPELINE_NEW.md` - Concise numbered-stage documentation
- `migrate_to_pipeline_structure.sh` - Migration script for existing installations

**Backed up**:

- `PIPELINE.md.backup` - Original documentation preserved

## Migration Steps

### Option 1: Automated Migration (Recommended)

```bash
# 1. Setup environment
source ./env_setup.sh /Volumes/MySSD/skicyclerun.i2i /Volumes/MySSD/models

# 2. Run migration script
./migrate_to_pipeline_structure.sh

# This will:
# - Move images/albums/* → pipeline/archive/albums/
# - Version metadata/master.json → pipeline/archive/metadata/master_v1_*.json
# - Move images/scaled/* → pipeline/scaled/
# - Move images/lora_processed/* → pipeline/lora_processed/
# - Move images/lora_final/* → pipeline/watermarked_final/
# - Create new empty pipeline/albums/ for new exports
# - Create new empty pipeline/metadata/ for new extractions
```

### Option 2: Manual Migration

```bash
# 1. Create new structure
mkdir -p $SKICYCLERUN_LIB_ROOT/pipeline/{archive/{albums,metadata},albums,metadata,scaled,lora_processed,watermarked_final}

# 2. Archive old albums
mv $SKICYCLERUN_LIB_ROOT/images/albums/* $SKICYCLERUN_LIB_ROOT/pipeline/archive/albums/

# 3. Version metadata
cp $SKICYCLERUN_LIB_ROOT/metadata/master.json $SKICYCLERUN_LIB_ROOT/pipeline/archive/metadata/master_v1_$(date +%Y%m%d).json

# 4. Move working directories
mv $SKICYCLERUN_LIB_ROOT/images/scaled $SKICYCLERUN_LIB_ROOT/pipeline/
mv $SKICYCLERUN_LIB_ROOT/images/lora_processed $SKICYCLERUN_LIB_ROOT/pipeline/
mv $SKICYCLERUN_LIB_ROOT/images/lora_final $SKICYCLERUN_LIB_ROOT/pipeline/watermarked_final
```

### Option 3: Fresh Start

```bash
# 1. Backup existing work
mv $SKICYCLERUN_LIB_ROOT/images $SKICYCLERUN_LIB_ROOT/images.backup
mv $SKICYCLERUN_LIB_ROOT/metadata $SKICYCLERUN_LIB_ROOT/metadata.backup

# 2. Create new structure
mkdir -p $SKICYCLERUN_LIB_ROOT/pipeline/{archive/{albums,metadata},albums,metadata,scaled,lora_processed,watermarked_final}

# 3. Start fresh with new exports
```

## Updated Workflow

### Stage 0: Archive (Before New Export)

```bash
python pipeline.py --stages cleanup
```

- Moves `pipeline/albums/*` → `pipeline/archive/albums/`
- Versions `pipeline/metadata/master.json` → `pipeline/archive/metadata/master_v{N}_{timestamp}.json`

### Stage 1: Export New Albums

```bash
osascript scripts/osxPhotoExporter.scpt
```

- **IMPORTANT**: Only select NEW albums (never re-export same album - causes duplicates!)
- Exports to: `pipeline/albums/[album_name]/`

### Stage 2: Extract Metadata

```bash
python pipeline.py --stages metadata_extraction
```

- Output: `pipeline/metadata/master.json`

### Stage 3: Preprocess Images

```bash
python pipeline.py --stages preprocessing
```

- Output: `pipeline/scaled/[album_name]/*.webp`

### Stage 4: Apply LoRA Styles

```bash
caffeinate -i python pipeline.py --stages lora_processing
```

- Output: `pipeline/lora_processed/[album_name]/*_{style}_{timestamp}.webp`

### Stage 5: Add Watermarks

```bash
python pipeline.py --stages post_lora_watermarking
```

- Output: `pipeline/watermarked_final/[album_name]/*.webp`

### Stage 6: Deploy to S3

```bash
python pipeline.py --stages s3_deployment
```

- Uploads from: `pipeline/watermarked_final/`
- To: `s3://skicyclerun.lib/albums/`

## Benefits

### 1. Clear Output Tracking

- Each stage has its own numbered directory
- Easy to see where data is at any point in pipeline
- No confusion about which directory to check

### 2. Prevents Duplicate Photos

- Stage 0 (archive) moves old albums before new exports
- Clear separation between old and new work
- Archive preserves history with versioned metadata

### 3. Easier Debugging

- Stage numbers match process flow
- Can inspect output at each stage
- Clear path: albums → scaled → lora_processed → watermarked_final → S3

### 4. Better Organization

- All pipeline work under `pipeline/` directory
- Archive keeps old work without deleting
- Metadata versioning tracks changes over time

## Verification

After migration, verify structure:

```bash
# Check new structure
ls -la $SKICYCLERUN_LIB_ROOT/pipeline/

# Should see:
# - archive/
# - albums/
# - metadata/
# - scaled/
# - lora_processed/
# - watermarked_final/

# Verify old work is archived
ls -la $SKICYCLERUN_LIB_ROOT/pipeline/archive/albums/
ls -la $SKICYCLERUN_LIB_ROOT/pipeline/archive/metadata/
```

## Troubleshooting

### Migration script fails

- Check `SKICYCLERUN_LIB_ROOT` is set: `printenv SKICYCLERUN_LIB_ROOT`
- Run `source ./env_setup.sh` first
- Ensure sufficient disk space

### Old directories remain

Safe to remove after verifying migration:

```bash
rmdir $SKICYCLERUN_LIB_ROOT/images  # If empty
rmdir $SKICYCLERUN_LIB_ROOT/metadata  # If empty
```

### Pipeline can't find files

Update main.py and other scripts to use new paths (already done in config).

## Files Modified

✅ **Updated**:

- `config/pipeline_config.json` - New path structure
- `scripts/osxPhotoExporter.scpt` - Exports to `pipeline/albums`
- `env_setup.sh` - No changes needed (uses SKICYCLERUN_LIB_ROOT)

📝 **Created**:

- `PIPELINE_NEW.md` - New concise documentation
- `migrate_to_pipeline_structure.sh` - Migration automation
- `PIPELINE_RESTRUCTURE.md` - This summary

💾 **Backed up**:

- `PIPELINE.md.backup` - Original documentation

## Next Steps

1. **Review this document**
2. **Run migration**: `./migrate_to_pipeline_structure.sh`
3. **Verify structure**: Check `pipeline/` directories
4. **Export new albums**: Use `osxPhotoExporter.scpt`
5. **Run pipeline**: `python pipeline.py --yes`

## Questions?

- Check `PIPELINE_NEW.md` for stage details
- Review `config/pipeline_config.json` for paths
- Run `python pipeline.py --check-config` to verify setup
