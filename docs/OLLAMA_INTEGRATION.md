# Ollama Enhanced Watermarking Integration

## Overview

Enhanced the pipeline watermarking with a 6-stage GPS-grounded analysis pipeline using Ollama LLMs. Generates rich, contextual watermarks based on GPS coordinates, nearby POIs, street context, and vision analysis.

## What Changed

### New Components

1. **`core/ollama_watermark_analyzer.py`** - NEW

   - 6-stage enhanced image analysis pipeline
   - GPS-grounded POI research using ministral-3:8b
   - Activity/scene analysis using llava:7b
   - Final content generation using mixtral:8x7b
   - Clean interface: `analyzer.analyze(image_path, metadata) -> result`

2. **`config/ollama_prompt_template.txt`** - NEW

   - Copied from `debug/llm_prompt_guide.txt`
   - Template for Stage 6 content generation
   - Includes WATERMARK section, POI context, Ground Zero street info

3. **Updated `config/pipeline_config.json`**

   - Added `ollama` configuration section:
     ```json
     "ollama": {
       "enabled": true,
       "endpoint": "http://localhost:11434",
       "models": {
         "poi_research": "ministral-3:8b",
         "vision": "llava:7b",
         "content_generation": "mixtral:8x7b"
       },
       "poi_research": { "temperature": 0.3, "num_predict": 250 },
       "vision": { "temperature": 0.3, "num_predict": 100 },
       "content_generation": {
         "temperature": 0.5,
         "top_p": 0.9,
         "num_predict": 400,
         "timeout": 300
       },
       "prompt_template": "config/ollama_prompt_template.txt"
     }
     ```

4. **Updated `pipeline.py::run_llm_image_analysis_stage()`**
   - Now checks if Ollama is available at startup
   - Uses enhanced 6-stage pipeline if Ollama running
   - Falls back to simple LLM analysis if Ollama unavailable
   - Logs which mode is being used

### Unchanged Components

- **`core/watermark_generator.py`** - NO CHANGES
  - Already checks for `metadata['llm_image_analysis']['watermark']` first
  - Falls back to location-based format if no LLM watermark
- **`core/watermark_applicator.py`** - NO CHANGES

  - No changes needed, uses generated watermark text

- **`core/llm_image_analyzer.py`** - KEPT
  - Simple fallback analyzer still available
  - Used when Ollama not available

## How It Works

### Enhanced Pipeline Flow (When Ollama Available)

```
Stage 1: GPS/EXIF Extraction  [Already done by metadata_extraction stage]
   ↓
Stage 2: POI Search           [Already done by metadata_extraction stage]
   ↓
Stage 3: POI Research         [NEW - GPS-grounded research using ministral-3:8b]
   • Research each of the 5 nearest POIs
   • Use GPS coordinates to ground the query
   • Ignore OSM classifications (avoid "artwork" bias)
   • Returns: type, description, what it's known for
   ↓
Stage 4: Image Scaling        [Skipped - already done by preprocessing stage]
   ↓
Stage 5: Activity Analysis    [NEW - Vision analysis using llava:7b]
   • Analyze: activity, scene_type, is_interior
   • Identify closest POI from photographer's perspective
   ↓
Stage 6: Content Generation   [NEW - Prose generation using mixtral:8x7b]
   • Uses prompt template with POI context
   • Includes Ground Zero street research
   • Generates: watermark sentence + full description
   • Text-only (no image sent to mixtral)
```

### Fallback Flow (When Ollama Not Available)

```
Simple LLM Analysis
   • Uses basic vision model
   • Generates simple watermark from location + date
   • Falls back to "Location, Country" format
```

## Usage

### Running the Pipeline

**With Ollama (Enhanced Mode):**

```bash
# 1. Start Ollama
ollama serve

# 2. Pull required models (if not already downloaded)
ollama pull ministral-3:8b
ollama pull llava:7b
ollama pull mixtral:8x7b

# 3. Run pipeline with enhanced watermarking
python pipeline.py --stages llm_image_analysis

# Output: ✅ Using enhanced Ollama 6-stage pipeline (GPS-grounded POI research)
```

**Without Ollama (Fallback Mode):**

```bash
# Ollama not running or config disabled
python pipeline.py --stages llm_image_analysis

# Output: ⚠️ Enhanced Ollama pipeline not available
#         Falling back to simple LLM analysis
```

### Configuration

**Enable/Disable Enhanced Pipeline:**

```json
{
  "ollama": {
    "enabled": true // Set to false to always use simple fallback
  }
}
```

**Customize Models:**

```json
{
  "ollama": {
    "models": {
      "poi_research": "ministral-3:8b", // POI research model
      "vision": "llava:7b", // Image analysis model
      "content_generation": "mixtral:8x7b" // Final content model
    }
  }
}
```

**Adjust Generation Parameters:**

```json
{
  "ollama": {
    "content_generation": {
      "temperature": 0.5, // Creativity (0.1-1.0)
      "top_p": 0.9, // Nucleus sampling
      "num_predict": 400, // Max tokens
      "timeout": 300 // Request timeout (seconds)
    }
  }
}
```

**Customize Prompt Template:**

```json
{
  "ollama": {
    "prompt_template": "config/ollama_prompt_template.txt"
  }
}
```

Edit `config/ollama_prompt_template.txt` to change:

- RULES section (no first person, etc.)
- WATERMARK section instructions
- How POI context is presented

## Output Schema

The enhanced analyzer stores results in `metadata['llm_image_analysis']`:

```json
{
  "watermark": "Steampunk HQ beckons visitors to immerse themselves in Victorian-era aesthetics and mechanical marvels",
  "description": "Full travel blog paragraph with POI context...",
  "primary_subject": "historic museum building with steampunk art",
  "scene_type": "urban",
  "is_interior": false,
  "closest_poi": {
    "name": "Steampunk HQ",
    "distance_m": 48.9,
    "research": "Steampunk HQ is a museum and art gallery..."
  },
  "model": "mixtral:8x7b",
  "llm_analysis_time": 19.89,
  "timing": {
    "poi_research": 12.93,
    "activity_analysis": 15.37,
    "content_generation": 19.89,
    "total": 56.48
  }
}
```

## Testing

### Test Enhanced Analyzer Standalone

```python
from core.ollama_watermark_analyzer import OllamaWatermarkAnalyzer
import json

# Load config
with open('config/pipeline_config.json') as f:
    config = json.load(f)

# Initialize analyzer
analyzer = OllamaWatermarkAnalyzer(config)

# Prepare metadata (from metadata_extraction stage)
metadata = {
    'gps': {'latitude': -45.102, 'longitude': 170.970},
    'location': {'city': 'Ōamaru', 'country': 'New Zealand'},
    'nearby_pois': [
        {'name': 'Steampunk HQ', 'type': 'attraction', 'distance_m': 48.9},
        {'name': 'Ōamaru Creek Rail Bridge', 'type': 'landmark', 'distance_m': 52.5}
    ]
}

# Run analysis
result = analyzer.analyze('path/to/image.jpg', metadata)

print(result['watermark'])
# Output: "Steampunk HQ beckons visitors to immerse themselves..."
```

### Test Pipeline Integration

```bash
# Run on single image
python pipeline.py --stages llm_image_analysis --sweep-path-contains IMG_2764 --sweep-limit 1

# Check output
cat pipeline/metadata/master.json | jq '.[] | select(.file_path | contains("IMG_2764")) | .llm_image_analysis'
```

### Debug Mode

Enable debug mode to save prompts:

```bash
python pipeline.py --stages llm_image_analysis --debug

# Saved to: pipeline/metadata/llm_prompt_request.json
```

## Debugging

### Check Ollama Availability

```bash
curl http://localhost:11434/api/tags
```

Expected: List of available models

### Check Models Installed

```bash
ollama list
```

Expected output should include:

- ministral-3:8b
- llava:7b
- mixtral:8x7b

### View Pipeline Logs

```bash
tail -f logs/pipeline_*.log
```

Look for:

- `✅ Using enhanced Ollama 6-stage pipeline` - Enhanced mode active
- `⚠️ Enhanced Ollama pipeline not available` - Fallback mode active

### Test Individual Stages

Use `debug/test_ollama_structured.py` for standalone testing:

```bash
python debug/test_ollama_structured.py path/to/image.jpg debug/llm_prompt_guide.txt
```

## Known Issues

1. **Geocoding Accuracy**

   - Nominatim sometimes returns wrong city
   - Solution: Using zoom level 12 for city, 18 for street
   - POI research helps validate location

2. **OSM Classification Bias**

   - OSM may classify museums as "artwork"
   - Solution: Research prompt ignores classification, uses GPS grounding

3. **Model Availability**
   - Requires ~16GB disk for all 3 models
   - Download with: `ollama pull <model_name>`

## Performance

**Enhanced Mode:**

- Stage 3 (POI Research): ~13s for 5 POIs
- Stage 5 (Vision Analysis): ~15s
- Stage 6 (Content Generation): ~20s
- **Total: ~50-60s per image**

**Fallback Mode:**

- Simple vision analysis: ~5-10s
- **Total: ~5-10s per image**

## Future Enhancements

- [ ] Cache POI research results (by name + GPS)
- [ ] Parallel POI research (5 POIs at once)
- [ ] Custom LoRA for location-specific content
- [ ] Multi-language watermark generation
- [ ] Automatic landmark classification from research

## Migration from Debug Script

The enhanced pipeline is extracted from `debug/test_ollama_structured.py`:

| Debug Script                | Integrated Component                                   |
| --------------------------- | ------------------------------------------------------ |
| `geocode_location()`        | Reuses existing `GeoExtractor`                         |
| `search_nearby_pois()`      | Reuses existing POI search                             |
| `research_primary_poi()`    | `OllamaWatermarkAnalyzer.research_poi()`               |
| `analyze_primary_subject()` | `OllamaWatermarkAnalyzer.analyze_activity()`           |
| `generate_final_content()`  | `OllamaWatermarkAnalyzer.generate_watermark_content()` |
| `main()` 6-stage loop       | `OllamaWatermarkAnalyzer.analyze()`                    |

The debug script remains available for standalone testing and experimentation.

## References

- Original implementation: `debug/test_ollama_structured.py`
- Prompt template: `config/ollama_prompt_template.txt`
- Configuration: `config/pipeline_config.json` (ollama section)
- Integration: `pipeline.py::run_llm_image_analysis_stage()`
