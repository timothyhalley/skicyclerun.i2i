# METADATA ARCHITECTURE - CONSOLIDATED & SIMPLIFIED

## ARCHITECTURAL DECISION

**Single Source of Truth: master.json**

All image metadata lives in one place with proper UPSERT semantics to prevent data loss.

---

## FILE STRUCTURE

### 1. **master.json** (Single Source of Truth)

**Location:** `pipeline/metadata/master.json`
**Purpose:** Central registry for ALL image metadata
**Access:** Via `MasterStore` class with UPSERT operations

**Structure:**

```json
{
  "/path/to/image.jpg": {
    "file_path": "/path/to/image.jpg",
    "file_name": "image.jpg",
    "created_at": "2025-12-04T17:00:00Z",

    "exif": {
      "date_taken": "2024-08-15 14:30:00",
      "date_taken_utc": "2024-08-15T18:30:00Z",
      "camera": "iPhone 15 Pro Max",
      "gps": { "latitude": 40.7484, "longitude": -73.9857 }
    },

    "location": {
      "display_name": "Empire State Building, Midtown Manhattan, New York, NY, United States",
      "address": {
        "road": "Fifth Avenue",
        "city": "New York",
        "state": "New York",
        "country": "United States"
      },
      "ollama_enhanced": {
        "enhanced_watermark": "Empire State Building and Bryant Park near Times Square",
        "enhanced_watermark_original": "エンパイアステートビルディングとブライアントパーク",
        "enhanced_watermark_english": "Empire State Building and Bryant Park",
        "basic_watermark": "New York, New York",
        "poi": "Empire State Building, Bryant Park, Times Square",
        "poi_en": "Empire State Building, Bryant Park, Times Square",
        "history": "Iconic Art Deco skyscraper built 1930-1931...",
        "enhanced_at": "2025-12-04T17:30:00Z"
      }
    },

    "pipeline": {
      "stages": [
        "metadata_extraction",
        "geocoding",
        "ollama_enhancement",
        "preprocessing",
        "lora_processing"
      ],
      "timestamps": {
        "metadata_extraction": "2025-12-01T10:00:00Z",
        "geocoding": "2025-12-01T10:05:00Z",
        "ollama_enhancement": "2025-12-04T17:30:00Z"
      }
    }
  }
}
```

**Key Points:**

- One entry per original image (keyed by file path)
- LoRA-processed images reference original via `source_path`
- `location.ollama_enhanced` added via UPSERT (never overwrites other data)
- MasterStore auto-saves after each update (atomic writes via temp file)

---

### 2. **geocode_cache.json** (API Response Cache)

**Location:** `pipeline/metadata/geocode_cache.json`
**Purpose:** Cache raw Nominatim API responses to avoid redundant API calls
**Access:** Internal to geocoding module

**Structure:**

```json
{
  "40.7484,-73.9857": {
    "display_name": "Empire State Building, Midtown Manhattan...",
    "address": {...},
    "cached_at": "2025-12-01T10:05:00Z"
  }
}
```

**Key Points:**

- Keep separate - this is API-level caching (lat/lon → location data)
- Reduces external API calls (Nominatim rate limits)
- Not merged into master.json (different key structure)

---

### 3. **watermarkLocationInfo.json** (DEPRECATED - Being Phased Out)

**Status:** ⚠️ **DEPRECATED** - Data migrated to master.json
**Action:** Run `debug/migrate_watermark_cache.py` to consolidate

This file is no longer used. All Ollama enhancements now live in:

```
master.json → [image_path] → location → ollama_enhanced
```

---

## CODE ARCHITECTURE

### MasterStore (core/master_store.py)

```python
store = MasterStore(master_path, auto_save=True)

# UPSERT operations (safe, no data loss)
store.update_entry(image_path, {"exif": {...}})
store.update_section(image_path, "location", {...})
store.mark_stage(image_path, "ollama_enhancement")

# Read operations
entry = store.get(image_path)
all_entries = store.list_paths()

# Auto-saves after each update with atomic write (temp file + rename)
```

### LocationEnhancementCache (core/ollama_location_enhancer.py)

```python
# Now wraps MasterStore instead of separate file
cache = LocationEnhancementCache(master_store)

# Get enhancement
enhanced = cache.get(image_path)
# Returns: location.ollama_enhanced dict or None

# Set enhancement (UPSERT into master.json)
cache.set(image_path, {
    'enhanced_watermark': '...',
    'poi': '...',
    'history': '...'
})
# Adds to master.json → [image_path] → location → ollama_enhanced
# Auto-saves via MasterStore
```

---

## WORKFLOW

### 1. **Image Import & Metadata Extraction**

```bash
python3 pipeline.py --stages metadata_extraction
```

- Extracts EXIF data (date, GPS, camera)
- Creates entry in master.json
- Marks stage: `metadata_extraction`

### 2. **Geocoding (converts GPS → Location)**

```bash
python3 pipeline.py --stages geocoding
```

- Calls Nominatim API (cached in geocode_cache.json)
- Stores raw location data in master.json → location
- Marks stage: `geocoding`

### 3. **Ollama Enhancement (intelligent watermarks)**

```bash
python3 debug/analyze_location_display.py --all
```

- Reads location from master.json
- Calls Ollama LLM for contextual analysis
- **UPSERTS** enhancement into master.json → location → ollama_enhanced
- Marks stage: `ollama_enhancement`
- **NO DATA LOSS** - merges with existing location data

### 4. **LoRA Processing**

```bash
python3 pipeline.py --stages lora_processing
```

- Creates artistic variants (not in master.json yet)
- LoRA images reference original via filename parsing

### 5. **Watermarking**

```bash
python3 pipeline.py --stages post_lora_watermarking
```

- For each LoRA image:
  1. Parse filename to find original image
  2. Lookup original in master.json
  3. Read location.ollama_enhanced for watermark text
  4. Apply dual-line watermark (enhanced + copyright)

---

## MIGRATION PLAN

### Step 1: Migrate Existing Data

```bash
python3 debug/migrate_watermark_cache.py
```

This will:

- Read watermarkLocationInfo.json
- UPSERT each entry into master.json
- Backup old file to watermarkLocationInfo.json.backup
- Preserve ALL existing data

### Step 2: Verify Migration

```bash
python3 -c "
from core.master_store import MasterStore
store = MasterStore('pipeline/metadata/master.json')
enhanced_count = sum(1 for e in store.data.values()
                     if isinstance(e.get('location'), dict)
                     and 'ollama_enhanced' in e['location'])
print(f'Enhanced entries in master.json: {enhanced_count}')
"
```

### Step 3: Test Watermarking

```bash
# Test on one album
python3 pipeline.py --stages post_lora_watermarking
```

### Step 4: Clean Up (AFTER verifying everything works)

```bash
rm pipeline/metadata/watermarkLocationInfo.json.backup
```

---

## BENEFITS

### 1. **Single Source of Truth**

- No data duplication
- One file to backup/restore
- Clear ownership of data

### 2. **UPSERT Semantics**

- Never overwrites existing data
- Safe concurrent updates
- Atomic writes (temp file + rename)

### 3. **Incremental Processing**

- Re-run Ollama enhancement anytime
- Only updates specific fields
- Preserves EXIF, geocoding, pipeline history

### 4. **Clear Separation**

- master.json: Image metadata (single source of truth)
- geocode_cache.json: API response cache (lat/lon → location)

### 5. **Better Performance**

- No duplicate JSON parsing
- MasterStore stays in memory
- Atomic writes prevent corruption

---

## TROUBLESHOOTING

### "No location metadata" errors

**Cause:** LoRA images don't have location in master.json
**Fix:** Location is stored on original image, not LoRA variant

- `postprocess_lora.py` looks up original via filename parsing
- Returns `location` with `ollama_enhanced` nested inside

### "No enhanced watermark"

**Cause:** Original image not yet enhanced by Ollama
**Fix:** Run enhancement tool

```bash
python3 debug/analyze_location_display.py --all
```

### "Data lost after re-running"

**Cause:** Old code overwrote entire file
**Fix:** New code uses UPSERT via MasterStore

- Each update merges with existing data
- Run migration script to consolidate

---

## FUTURE ENHANCEMENTS

### Possible: Merge geocode_cache into master.json?

**Current:** Separate file keyed by "lat,lon"
**Pros of merging:**

- One file to manage
- Could dedupe location data

**Cons of merging:**

- Different key structure (lat/lon vs file path)
- API cache vs image metadata (different concerns)
- Nominatim responses are large (bloats master.json)

**Decision:** Keep separate for now (different concerns)

---

## SUMMARY

**BEFORE (Fragmented):**

- master.json (image metadata)
- geocode_cache.json (API responses)
- watermarkLocationInfo.json (Ollama enhancements) ← **DUPLICATE DATA**

**AFTER (Consolidated):**

- master.json (image metadata + Ollama enhancements) ← **SINGLE SOURCE**
- geocode_cache.json (API responses) ← **DIFFERENT CONCERN**

**Key Change:**

```python
# OLD: Separate cache file (overwrites on save)
cache = LocationEnhancementCache('watermarkLocationInfo.json')

# NEW: UPSERT into master.json (no data loss)
master_store = MasterStore('master.json', auto_save=True)
cache = LocationEnhancementCache(master_store)
```

**Result:** Simpler, safer, single source of truth.
