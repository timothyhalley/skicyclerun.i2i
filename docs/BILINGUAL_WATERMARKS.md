# Bilingual Watermark Enhancement

## Overview

The watermarking system now supports **bilingual watermarks** that preserve original language (Japanese, Chinese, Korean, etc.) while providing English translations.

## Example: Tokyo Shibaura Location

### Input Address

```
海岸一丁目, 海岸, 港区, 東京都, 104-0046, 日本
(Kaigan 1-chome, Kaigan, Minato-ku, Tokyo, 104-0046, Japan)
```

### What the LLM Discovers

**Breakdown:**

- `海岸一丁目` (Kaigan ichi-dōme) - Specific block in Minato Ward
- `海岸` (Kaigan) - Means "coast" or "seaside"
- `港区` (Minato-ku) - Minato Ward, special ward in Tokyo
- `東京都` (Tōkyō-to) - Tokyo Metropolis
- `104-0046` - Postal code
- `日本` (Nihon) - Japan

**Nearby POIs:**

- Shibaura Pier (芝浦ふ頭)
- Shibaura-futō Seaside Park (芝浦ふ頭海浜公園)
- Tokyo Bay waterfront
- Shibaura Institute of Technology

**Contextual Watermark:**

```
"Shibaura Coastline, Tokyo Bay: Amidst the Urban Landscape of Minato-ku, Japan"
```

## Enhanced Output Structure

### JSON Fields Returned

```json
{
  "display_name": "海岸一丁目, 海岸, 港区, 東京都, 104-0046, 日本",
  "display_name_en": "Kaigan District, Minato, Tokyo, Japan",
  "poi": "芝浦ふ頭海浜公園, 東京湾",
  "poi_en": "Shibaura Pier Seaside Park, Tokyo Bay",
  "history": "Coastal area in Minato Ward with scenic waterfront views of Tokyo Bay",
  "basic_watermark": "港区: 芝浦海岸線",
  "basic_watermark_en": "Minato: Shibaura Coastline",
  "enhanced_watermark": "港区: 芝浦海岸線 (Minato: Shibaura Coastline)",
  "enhanced_watermark_original": "港区: 芝浦海岸線",
  "enhanced_watermark_english": "Minato: Shibaura Coastline"
}
```

## Display Format

The analyzer now shows:

```
Display Name: 海岸一丁目, 海岸, 港区, 東京都, 104-0046, 日本
Display Name (EN): Kaigan District, Minato, Tokyo, Japan

POI: 芝浦ふ頭海浜公園, 東京湾
POI (EN): Shibaura Pier Seaside Park, Tokyo Bay

History: Coastal area in Minato Ward with scenic waterfront views of Tokyo Bay

📍 Basic Watermark: 港区: 芝浦海岸線
📍 Basic Watermark (EN): Minato: Shibaura Coastline

✨ Enhanced Watermark (Bilingual): 港区: 芝浦海岸線 (Minato: Shibaura Coastline)
   🌏 Original: 港区: 芝浦海岸線
   🌐 English: Minato: Shibaura Coastline
```

## How It Works

### 1. LLM Prompt Enhancement

The Ollama prompt now requests **5 fields** instead of 3:

- `watermark_display_name` - Original language
- `watermark_display_name_en` - English translation
- `notable_poi` - Original language POIs
- `notable_poi_en` - English POI translations
- `brief_history` - Always in English

### 2. Intelligent Translation

The LLM (mixtral:8x7b) analyzes the location and:

- Identifies the meaning of Japanese/Chinese/Korean characters
- Researches nearby landmarks and features
- Provides proper romanization (not just phonetic)
- Creates contextual watermarks with cultural significance

### 3. Bilingual Formatting

Enhanced watermarks combine both languages:

```
{original} ({english})
```

If already in English, only shows once (no duplication).

### 4. Cache Storage

All versions saved to `watermarkLocationInfo.json`:

- Original language versions for Japanese/international sites
- English translations for accessibility
- Bilingual combined format for display

## Example Comparisons

### Japanese Location

```
Original:  東京: 渋谷
English:   Tokyo: Shibuya
Bilingual: 東京: 渋谷 (Tokyo: Shibuya)
```

### English Location (No Duplication)

```
Original:  Barcelona: Sagrada Familia
English:   Barcelona: Sagrada Familia
Bilingual: Barcelona: Sagrada Familia
```

### With Multiple POIs

```
Original:  港区: 芝浦ふ頭海浜公園 & 東京湾
English:   Minato: Shibaura Pier Park & Tokyo Bay
Bilingual: 港区: 芝浦ふ頭海浜公園 & 東京湾 (Minato: Shibaura Pier Park & Tokyo Bay)
```

## Testing

### Delete Cache and Rerun

```bash
rm /Volumes/MySSD/skicyclerun.i2i/pipeline/metadata/watermarkLocationInfo.json
python3 debug/analyze_location_display.py
```

### Expected Output for Tokyo Images

- Preserves Japanese characters (港区, 東京, etc.)
- Provides accurate English translations
- Identifies contextual POIs (parks, landmarks, districts)
- Creates meaningful watermarks with local significance

## Benefits

1. **Cultural Preservation**: Maintains original language for authenticity
2. **Accessibility**: English translations for international viewers
3. **Context**: POIs and history provide location meaning
4. **Flexibility**: Watermark applicator can use original, English, or bilingual
5. **Smart Caching**: All versions stored for pipeline reuse

## Future Enhancements

- Support for Chinese (Simplified/Traditional)
- Korean locations with Hangul/Romanization
- Arabic script support
- Configurable watermark format (original-only, English-only, or bilingual)
