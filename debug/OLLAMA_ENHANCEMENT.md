# Ollama Location Enhancement Workflow

## Overview

This system uses a local Ollama LLM to intelligently format location names for photo watermarks, extracting meaningful landmarks and context instead of generic street names.

## Architecture

```
Master Store (master.json)
    ↓
Ollama Enhancement (analyze_location_display.py)
    ↓
Enhanced Cache (watermarkLocationInfo.json)
    ↓
Pipeline Watermarking (pipeline.py --stages post_lora_watermarking)
    ↓
Final Watermarked Images
```

## Components

### 1. `core/ollama_location_enhancer.py`

- **OllamaLocationEnhancer**: Calls local Ollama to format location names
- **LocationEnhancementCache**: Manages persistent cache of enhanced locations
- Uses JSON format for reliable LLM responses

### 2. `debug/analyze_location_display.py`

- Samples 10 random images per album from master.json
- Shows original display_name, address components, heuristic format
- Calls Ollama to enhance each location
- Saves results to `watermarkLocationInfo.json`
- Caches results for future use

### 3. `core/watermark_applicator.py`

- Updated `_apply_two_line_watermark()` to check cache first
- Falls back to original display_name if no enhancement available
- Seamlessly integrates with existing pipeline

## Setup

### Prerequisites

1. **Install Ollama**

   ```bash
   # macOS
   brew install ollama

   # Or download from https://ollama.ai
   ```

2. **Pull llama3.2 model**

   ```bash
   ollama pull llama3.2:latest
   ```

3. **Start Ollama server**

   ```bash
   ollama serve
   # Keep running in background
   ```

4. **Test connection**
   ```bash
   python debug/test_ollama.py
   ```

## Usage

### Step 1: Analyze and Enhance Locations

```bash
python debug/analyze_location_display.py
```

This will:

- Load master.json with all image metadata
- Sample 10 images per album
- For each image:
  - Show original display_name and address components
  - Show heuristic formatting (rule-based)
  - Call Ollama to create intelligent display name
  - Extract POI and historical context
  - Cache results in watermarkLocationInfo.json

**Output Example:**

```
1. IMG_5238.jpeg
   📍 Country: CA
   🏷️  Original display_name:
      Banff-Windermere Parkway, Radium Hot Springs, Regional District of East Kootenay, British Columbia, V0A 1M0, Canada
   🗺️  Address components:
      Road: Banff-Windermere Parkway
      Town: Radium Hot Springs
      State: British Columbia
      Country: Canada
   💡 HEURISTIC PROPOSED NAME:
      Radium Hot Springs, BC, Canada
   🤖 OLLAMA ENHANCED:
      Display: Radium Hot Springs, British Columbia
      POI: Near Kootenay National Park entrance
      Context: Mountain resort town known for hot springs and Rocky Mountain access
```

### Step 2: Review Cache

The enhanced data is saved to:

```
/Volumes/MySSD/skicyclerun.i2i/pipeline/metadata/watermarkLocationInfo.json
```

Structure:

```json
{
  "/path/to/image.jpg": {
    "enhanced_display_name": "Radium Hot Springs, British Columbia",
    "poi_summary": "Near Kootenay National Park entrance",
    "historical_context": "Mountain resort town...",
    "original_display_name": "Banff-Windermere Parkway, Radium Hot Springs..."
  }
}
```

### Step 3: Apply Watermarks

```bash
python pipeline.py --stages post_lora_watermarking
```

The watermark applicator will:

1. Check `watermarkLocationInfo.json` for enhanced location
2. Use `enhanced_display_name` if available
3. Fall back to original display_name if not cached

### Step 4: Iterate

- Re-run `analyze_location_display.py` to add more albums
- Cache is persistent and cumulative
- Edit cache JSON directly if you want to override specific locations

## Configuration

### Ollama Settings (in code)

```python
enhancer = OllamaLocationEnhancer(
    config,
    model="llama3.2:latest",  # Model to use
    host="http://localhost:11434"  # Ollama server
)
```

### Prompt Customization

Edit `_build_prompt()` in `ollama_location_enhancer.py` to change:

- Number of components (currently max 4)
- Priority order (currently: Landmarks > Towns > Neighborhoods > States)
- Style preferences
- POI/historical context requirements

### Cache Location

Set in `pipeline_config.json`:

```json
{
  "paths": {
    "metadata_dir": "{pipeline_base}/metadata"
  }
}
```

Cache file: `{metadata_dir}/watermarkLocationInfo.json`

## Advantages Over Heuristics

| Aspect             | Heuristics                          | Ollama Enhancement           |
| ------------------ | ----------------------------------- | ---------------------------- |
| Street filtering   | Rule-based (parkway, highway, etc.) | Understands context and fame |
| Landmark detection | None                                | Identifies notable places    |
| Name selection     | First component or city             | Prioritizes meaningful names |
| International      | Basic Latin filtering               | Cultural awareness           |
| POI context        | None                                | Extracts nearby landmarks    |
| Historical info    | None                                | Provides cultural context    |

## Troubleshooting

### Ollama not responding

```bash
# Check if running
ps aux | grep ollama

# Restart
pkill ollama
ollama serve
```

### Model not found

```bash
ollama list
ollama pull llama3.2:latest
```

### Slow generation

- First request pulls model into memory (30s)
- Subsequent requests are faster (2-5s)
- Consider using smaller model: `llama3.2:1b`

### JSON parsing errors

- LLM occasionally outputs invalid JSON
- Code includes fallback to heuristic formatting
- Cache preserves successful enhancements

### Cache out of sync

```bash
# Delete cache to regenerate
rm /Volumes/MySSD/skicyclerun.i2i/pipeline/metadata/watermarkLocationInfo.json

# Re-run analysis
python debug/analyze_location_display.py
```

## Performance

- **Ollama latency**: 2-5 seconds per location (after model loaded)
- **Cache hit rate**: 100% for previously processed images
- **Sample size**: 10 images/album keeps analysis fast
- **Parallel potential**: Could batch Ollama calls for speed (future enhancement)

## Future Enhancements

1. **Batch processing**: Call Ollama for multiple locations in parallel
2. **Model selection**: Allow users to choose model via config
3. **Confidence scores**: Rate enhancement quality, flag for review
4. **Manual overrides**: UI to review/edit enhanced names
5. **Multilingual**: Generate display names in multiple languages
6. **Smart defaults**: Use heuristics for common locations, Ollama for complex ones
