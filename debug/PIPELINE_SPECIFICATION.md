# Image Analysis Pipeline Specification

## Overview

Six-stage pipeline for GPS-grounded image analysis with POI research and LLM-generated watermark content.

---

## STAGE 1: EXIF Extraction & Geocoding

**Purpose:** Extract GPS from image and reverse geocode to location details

**Inputs:**

- Image file path

**Outputs (saved to JSON):**

```json
{
  "gps": {
    "latitude": 1.279436,
    "longitude": 103.843849,
    "heading": 324.09,
    "cardinal": "NW"
  },
  "location": {
    "city": "Lisboa",
    "state": null,
    "country": "Portugal",
    "street_address": "Rua do Comércio",
    "road": "Rua do Comércio",
    "house_number": "12"
  }
}
```

**Rules:**

- Extract only: latitude, longitude, heading, cardinal direction
- Reverse geocode GPS to get city, state, country
- **NEW**: Get street address (road + house number) for urban grounding
- Street address becomes "Ground Zero" for urban scenes
- No altitude, no camera settings, no timestamps
- Save to `metadata['gps']` and `metadata['location']`

---

## STAGE 2: POI Search

**Purpose:** Find nearby Points of Interest using GPS coordinates

**Inputs:**

- GPS coordinates from Stage 1
- Search radius: 300m

**Outputs (saved to JSON):**

```json
{
  "pois": [
    {
      "name": "Maxwell Reserve",
      "classification": "hotel",
      "distance_m": 19.0
    }
  ]
}
```

**Rules:**

- Use Overpass API with retry logic (3 servers)
- Calculate distance using Haversine formula
- Sort by distance (closest first)
- Limit to 5 closest POIs
- Deduplicate by name
- Save to `metadata['pois']` with distance_m field
- **Serialize JSON after this stage**

---

## STAGE 3: POI Research

**Purpose:** Get contextual information about ALL POIs to provide grounding

**Why this matters:** Research helps qualify what type of place a POI is (e.g., "António Victor" becomes "local pastry shop with groceries" instead of generic "landmark")

**Inputs:**

- POI list from Stage 2 (ALL 5 POIs)
- Location data (city, country)

**Outputs (MERGED into existing POI nodes):**

```json
{
  "pois": [
    {
      "name": "Maxwell Reserve",
      "classification": "hotel",
      "distance_m": 19.0,
      "research": "The Maxwell Reserve is a hotel located in Singapore, Singapore. It was built in 1936..."
    }
  ]
}
```

**Rules:**

- Research ALL POIs from Stage 2 (not just primary)
- Use ministral-3:8b with simple prompt: "What do you know about [POI name] in [city], [country]?"
- Add "research" field to existing POI object (DO NOT create separate pois_with_research array)
- Keep description brief (2-3 sentences)
- Temperature: 0.2 (factual)
- Token limit: 150
- **Serialize JSON after this stage**

---

## STAGE 4: Image Scaling

**Purpose:** Resize image for LLM processing

**Inputs:**

- Original image file

**Outputs (saved to JSON):**

```json
{
  "image_info": {
    "original_size": "4032x3024",
    "scaled_size": "1024x768",
    "is_panorama": false
  }
}
```

**Rules:**

- Standard images: max 1024px on longest side
- **Serialize JSON after this stage**
- Panoramas (aspect > 2.0 or < 0.5): max 1536px on longest side
- JPEG quality: 85
- Convert to RGB
- Return base64 string for Stage 5

---

## STAGE 5: Image Analysis

**Purpose:** Detailed visual analysis of photo content

**Inputs:**

- Base64 image from Stage 4
- POI list from Stage 2 (for location context)

**Outputs (saved to JSON):**

```json
{
  "primary_subject": {
    "primary_subject": "Blue and white colonial building with French windows",
    "secondary_elements": "Well-maintained garden, palm trees, clear sky",
    "location_metadata": "Singapore, Singapore",
    "nearby_landmarks": "Chinatown, The Duxton hotel",
    "atmosphere": "Serene colonial elegance",
    "activity": "No visible activity, quiet street scene",
    "style": "Daytime architectural photography",
    "scene_type": "urban/historic",
    "is_interior": false,
    "closest_poi": {
      "name": "The Duxton",
      "classification": "hotel",
      "distance_m": 15.2
    }
  }
}
```

**Required Categories:**

1. **Primary Subject** - Main focus (person, object, landmark)
2. **Secondary Elements** - Supporting context (background, surroundings)
3. **Location Metadata** - City, state/province, country
4. **Nearby Landmarks** - Recognizable POIs visible or contextual
5. **Atmosphere/Mood** - Lighting, weather, emotional tone
6. **Activity/Action** - Human or environmental movement
7. **Style/Medium** - Photo type (portrait, landscape, aerial, long exposure)

**Additional Fields:**

- `scene_type`: urban/nature/historic/transit/beach/waterfront/mountain/other
- `is_interior`: true/false
- `closest_poi`: Closest POI from Stage 2 (photographer location)

**Rules:**

- Use llava:7b (fast visual analysis)
- Temperature: 0.3
- Token limit: 150
- Prompt must request ALL 7 categories
- No biased examples (caused subway hallucination)
- **Serialize JSON after this stage**

---

## STAGE 6: Content Generation

**Purpose:** Generate travel blog description and watermark content

**Inputs:**

- All metadata from Stages 1-5
- POI research from Stage 3
- Image analysis from Stage 5
- Prompt template file

**Outputs (saved to JSON):**

```json
{
  "final_content": {
    "raw_response": "...",
    "description": "The charming blue and white building...",
    "summation": "Duxton Hill's blue and white colonial building...",
    "watermark_line1": "Duxton Hill's colonial gem, steps from the historic Duxton hotel",
    "watermark_line2": "Singapore, Singapore"
  }
}
```

**Rules:**

- **NO VISION MODEL** - use text-only model (qwen3-next:80b)
- Image already analyzed in Stage 5 - work from metadata only
- Temperature: 0.5
- Token limit: 250
- Response format: Direct prose after "DESCRIPTION:"
- **POI list MUST include research context**, not just names
- Interior/Exterior must show as "Interior photo" or "Exterior photo", NOT boolean
- **Serialize JSON after this stage (final)**
- **KNOWN ISSUE**: qwen3-next:80b frequently returns empty (130-180s, no timeout but rejection)

**Writing Style Rules:**

- ❌ NO "this photo was taken..."
- ❌ NO first person ("I", "we", "you")
- ✅ Direct, engaging third-person prose
- ✅ Connect primary subject to nearby landmarks
- ✅ Use historical context from POI research
- ✅ Concise and crisp (not rambling)

**Prompt Structure:**

```text
LOCATION: [city, country]
📍 GROUND ZERO: [street address], [city]  (for urban scenes only)

WHAT YOU SEE IN PHOTO: [Stage 5 primary_subject]
Scene type: [Stage 5 scene_type]
[Interior photo OR Exterior photo]

NEARBY LANDMARKS (with context):
• [POI 1 name] ([classification]): [research context]
• [POI 2 name] ([classification]): [research context]
• [POI 3 name] ([classification]): [research context]
• [POI 4 name] ([classification]): [research context]
• [POI 5 name] ([classification]): [research context]

CONTEXT ABOUT PRIMARY LANDMARK:
[Research from closest/most significant POI]

Write a travel blog paragraph about this scene. Include the nearby landmarks and what's happening in the photo.

DESCRIPTION:
```

**Watermark Extraction:**

- `watermark_line1`: First sentence of description (or manually specified)
- `watermark_line2`:
  - US/Canada: "City, State, Country"
  - Others: "City, Country"

---

## JSON Output Structure

Final debug JSON saved to `logs/{image_name}_debug.json`:

```json
{
  "image_name": "IMG_1119",
  "timestamp": "2025-12-13T21:41:45",
  "gps": { ... },
  "location": { ... },
  "pois": [
    {
      "name": "...",
      "classification": "...",
      "distance_m": 0.0,
      "research": "..."
    }
  ],
  "image_info": { ... },
  "primary_subject": { ... },
  "final_content": { ... },
  "timing": {
    "stage1_gps": 0.01,
    "stage2_poi_search": 0.73,
    "stage3_poi_research": 23.44,
    "stage4_scaling": 0.16,
    "stage5_subject_analysis": 4.02,
    "stage6_generation": 245.26,
    "total": 277.47
  }
}
```

**CRITICAL:** Stage 3 adds "research" field to existing POI objects in the "pois" array. DO NOT create a separate "pois_with_research" array.

---

## Models Used

- **Stage 3**: llava:7b (text generation for POI research)
- **Stage 5**: llava:7b (vision model for image analysis)
- **Stage 6**: qwen3-next:80b (text-only for prose generation)

---

## Known Issues & Solutions

### Issue: qwen3-vl:32b Returns Empty

- **Cause**: Chain-of-thought overhead ("Thinking...") uses all tokens
- **Solution**: Use text-only models for Stage 6 (no image needed)

### Issue: POI Distances Trigger Obsessive Analysis

- **Cause**: LLMs fixate on calculating/recalculating distances
- **Solution**: Include distances in internal metadata, optionally hide from prompt

### Issue: Stop Sequences Kill Output

- **Cause**: ""}}"" in JSON template triggers immediate stop
- **Solution**: Use simple format (DESCRIPTION:) instead of JSON in prompt

### Issue: Model Rambling/Incomplete

- **Cause**: Token limit too high allows rambling, too low cuts off
- **Solution**: 250 tokens for Stage 6 forces conciseness

---

## Deviation Policy

**DO NOT change this specification without explicit user permission.**

If something seems wrong or could be improved:

1. Point out the specific issue
2. Explain the proposed change
3. Wait for approval
4. Document the change in this file
