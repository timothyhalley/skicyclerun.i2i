# QUICK START: Consolidated Metadata Architecture

## What Changed

### BEFORE (Bad - Data Loss Risk)

- 3 separate files with duplicate data
- watermarkLocationInfo.json overwrote data on every save
- No UPSERT - entire file replaced

### AFTER (Good - Safe UPSERT)

- **master.json** = Single source of truth (UPSERT semantics)
- **geocode_cache.json** = API cache only (different concern)
- LocationEnhancementCache now wraps MasterStore (auto-save, atomic writes)

## Migration Steps

### 1. Migrate your overnight Ollama job data

```bash
python3 debug/migrate_watermark_cache.py
```

This will:

- Read watermarkLocationInfo.json (391 entries from your overnight run)
- UPSERT each into master.json under location.ollama_enhanced
- Backup old file (no data loss!)

### 2. Verify migration worked

```bash
python3 debug/analyze_location_display.py --sample 3
```

Should show enhancements loaded from master.json

### 3. Continue processing remaining images

```bash
python3 debug/analyze_location_display.py --all
```

Will UPSERT new enhancements (no data loss on existing 391)

### 4. Run watermarking

```bash
python3 pipeline.py --stages post_lora_watermarking
```

Reads from master.json → location → ollama_enhanced

## Technical Details

### master.json Structure

```json
{
  "/path/to/IMG_1234.jpg": {
    "exif": {...},
    "location": {
      "display_name": "...",
      "address": {...},
      "ollama_enhanced": {
        "enhanced_watermark": "Landmark and POI description",
        "poi": "...",
        "history": "...",
        "enhanced_at": "2025-12-04T17:30:00Z"
      }
    },
    "pipeline": {"stages": [...]}
  }
}
```

### Code Changes

```python
# OLD
cache = LocationEnhancementCache('watermarkLocationInfo.json')
cache.set(path, data)  # Overwrites entire file
cache.save()           # Data loss risk

# NEW
master_store = MasterStore('master.json', auto_save=True)
cache = LocationEnhancementCache(master_store)
cache.set(path, data)  # UPSERT into master.json (auto-saves)
```

## Why This is Better

1. **Single Source of Truth**: master.json has everything
2. **UPSERT Semantics**: Updates merge with existing data (no overwrites)
3. **Atomic Writes**: Temp file + rename (no corruption)
4. **Auto-Save**: MasterStore saves after each update
5. **No Duplication**: One place for Ollama enhancements

## Your Data is Safe

- Migration script backs up watermarkLocationInfo.json
- MasterStore uses UPSERT (never deletes existing data)
- Re-running analyze_location_display.py is now safe (adds/updates only)

Read METADATA_ARCHITECTURE.md for full details.
