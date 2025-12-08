# LLM Image Analysis Prompt Template

## Current Prompt Structure

```python
prompt = f"""Analyze this image and provide detailed structured JSON output.

CONTEXT - Geographic data from GPS and POI search:
Location: {location_formatted}
Nearby Points of Interest:
{poi_context if poi_context else "  - No POI data available"}

CRITICAL: Use the GPS location context to ground your analysis. The location data tells you what COUNTRY, REGION, and CITY the photo was taken in. Use this to correctly interpret what you see.

YOUR TASK:

1. **description**: Comprehensive factual analysis grounded in GPS location
   - START by considering the GPS location context to correctly identify what you see
   - Interpret ALL visual elements (signs, terrain, architecture, activities) within the ACTUAL geographic context provided
   - Focus on the POI/subject ITSELF: its history, architecture, cultural significance, societal role
   - Include origins (year built, architect, design influences)
   - Cultural or civic relevance (what role it played/plays in society)
   - Notable events, restorations, transformations, or relocations
   - Current status and modern legacy
   - Provide multi-sentence factual detail (5-10 sentences minimum)

2. **primary_subject**: Descriptive phrase identifying the main subject
   - Use descriptive phrases, NOT single words
   - Examples: "Victorian clock in Melbourne Town Hall", "Street lined with outdoor cafes", "Historic fishing vessel on beach"
   - Be specific and contextual

3. **watermark**: Concise factual identifier GROUNDED in GPS location
   - **Maximum length**: ≤10 words OR ≤100 characters
   - **Schema**: {POI or landmark}, {city or region from GPS context}
   - **MUST include geographic location** from GPS context - use the actual country/region/city provided
   - **Content**: Must reference the actual subject/POI from description and primary_subject
   - **Tone**: Factual and neutral - NO promotional adjectives (beautiful/amazing/iconic)
   - **Clarity**: Simple wording suitable for bottom-of-image overlay - no complex clauses
   - **Geographic grounding**: Always anchor watermark to the GPS location provided (NOT generic "home interior" or missing location)

STRICT RULES - ZERO TOLERANCE:

FORBIDDEN PHRASES (will be rejected):
- "Photo taken at..."
- "Located near..."
- "This is a photo of..."
- "Image shows..."
- "Picture taken..."
- "The image depicts..."
- "This image shows..."
- "The photo displays..."
- "Visible in the image..."
- Any reference to the act of photography, the photographer, or the image itself
- NO leading newlines or whitespace in description

REQUIRED CONTENT:
- GROUND EVERYTHING in the provided GPS location context FIRST - use the actual country/region/city to correctly interpret what you see
- Description MUST start directly with the subject identification (NO preamble like "The image depicts...")
- Analyze what you SEE: landmarks, architecture, natural features, people, activities, signage, atmosphere
- Interpret ALL visual elements within the provided geographic context - use the location data to understand what you're seeing
- If recognizable landmark/POI: provide historical background (year established, architect, origins, significance)
- If scene/activity: describe the setting, cultural context, and what makes it notable in that location
- If natural feature: describe the landscape, geological/ecological significance, regional importance
- If person/people: focus on the setting, activity, cultural context of the location
- Multi-sentence factual detail (minimum 5 sentences) appropriate to what the image actually shows
- Watermark MUST include the actual geographic location from GPS context (the country/region/city provided in location data)

FACTUAL ONLY:
- NO promotional language (forbidden: luxurious/stunning/amazing/beautiful/perfect/wonderful/stay/visit/explore/enjoy)
- NO opinions or subjective descriptions
- ONLY verifiable facts, observable details, and historical information

EXAMPLES:

BAD ❌:
"description": "Photo taken at The Big Clock in Melbourne."

BAD ❌:
"description": "Located near Federation Square, this clock is visible in the image."

GOOD ✅:
"description": "The Big Clock is a historic landmark in Melbourne's city center, dating back to 1878 as part of Melbourne Town Hall designed by architect William Wardell. Originally serving as the official time standard for the city, it was used by railways, banks, and citizens during the Victorian era. The clock features a 12-meter diameter face with gold-toned brass and Roman numerals, embodying Victorian opulence and civic pride. In 2001, it was relocated to Federation Square as part of cultural preservation efforts, symbolizing Melbourne's blend of historical heritage and modern identity. The clock remains manually wound, maintaining its Victorian-era craftsmanship."

Return ONLY valid JSON with this exact structure:
{{
  "llm_model": "{self.model}",
  "llm_analysis_time": 0.0,
  "description": "",
  "primary_subject": "",
  "watermark": ""
}}

CRITICAL JSON FORMATTING RULES:
- Output MUST be valid JSON (parseable by json.loads())
- NO markdown formatting in values (NO **, __, *, `, #, etc.)
- NO unescaped quotes, newlines, or control characters in string values
- Use PLAIN TEXT ONLY in all fields
- If text needs emphasis, use CAPITAL LETTERS not markdown

Field requirements:
- llm_model: Model name (auto-filled)
- llm_analysis_time: Processing time in seconds (auto-filled)
- description: Multi-sentence factual analysis (5-10 sentences) focusing on POI itself - history, architecture, cultural significance, societal role. NO photo references. PLAIN TEXT ONLY.
- primary_subject: Descriptive phrase (e.g., "Victorian clock in Melbourne Town Hall"). PLAIN TEXT ONLY.
- watermark: 10-word factual summary with specific identification. PLAIN TEXT ONLY.

JSON output:"""
```

## Key Changes from Previous Version

### 1. Banned Generic Phrasing

- Explicitly lists FORBIDDEN PHRASES that reference photography
- Forces focus on POI itself, not the act of capturing it

### 2. Required Historical & Societal Context

- Mandates: origins, year built, architect, design influences
- Requires: cultural/civic relevance and societal role
- Demands: notable events, restorations, current status

### 3. Structured Multi-Sentence Output

- Minimum 5 sentences required in description
- Must include historical background
- Must include cultural significance
- Must separate visual identification from historical context

### 4. Strict Rules Section

- Zero tolerance for photo-reference phrases
- Clear examples of BAD vs GOOD output
- Explicit requirements for factual historical detail

## Expected Output Quality

### Before (REJECTED):

```json
{
  "description": "Photo taken at The Big Clock in Melbourne.",
  "primary_subject": "clock",
  "watermark": "Clock, Melbourne"
}
```

### After (EXPECTED):

```json
{
  "description": "The Big Clock is a historic landmark in Melbourne's city center, dating back to 1878 as part of Melbourne Town Hall designed by architect William Wardell. Originally serving as the official time standard for the city, it was used by railways, banks, and citizens during the Victorian era. The clock features a 12-meter diameter face with gold-toned brass and Roman numerals, embodying Victorian opulence and civic pride. In 2001, it was relocated to Federation Square as part of cultural preservation efforts, symbolizing Melbourne's blend of historical heritage and modern identity. The clock remains manually wound, maintaining its Victorian-era craftsmanship.",
  "primary_subject": "The Big Clock, Victorian-era public timepiece",
  "watermark": "The Big Clock, Melbourne Town Hall, Federation Square, 1878"
}
```

## Implementation Location

File: `/Users/timothyhalley/Projects/skicyclerun.i2i/core/llm_image_analyzer.py`

Function: `_build_prompt()`

Lines: ~57-130
