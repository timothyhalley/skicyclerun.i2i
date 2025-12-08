"""
LLM Image Analyzer
Analyzes images using ministral-3:8b vision model via Ollama
Generates structured JSON output with description, primary subject, and watermark
"""

import base64
import json
import time
import requests
from pathlib import Path
from PIL import Image
from typing import Dict, Optional, List
from io import BytesIO


class LLMImageAnalyzer:
    """Analyze images with vision LLM using ministral-3:8b"""
    
    def __init__(self, endpoint: str = "http://localhost:11434", model: str = "ministral-3:8b"):
        """
        Initialize LLM image analyzer
        
        Args:
            endpoint: Ollama API endpoint
            model: Vision model to use (ministral-3:8b)
        """
        self.endpoint = endpoint.rstrip('/')
        self.model = model
        self.generate_url = f"{self.endpoint}/api/generate"
    
    def _encode_image_base64(self, image_path: str) -> str:
        """
        Encode image as base64 string for LLM input
        
        Args:
            image_path: Path to image file
            
        Returns:
            Base64-encoded image string
        """
        with Image.open(image_path) as img:
            # Convert to RGB if needed (e.g., for PNG with alpha)
            img = img.convert("RGB")
            
            # Resize if too large (vision models have limits)
            max_size = 1024
            if max(img.size) > max_size:
                img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            
            # Encode as JPEG bytes then base64
            buffered = BytesIO()
            img.save(buffered, format="JPEG", quality=85)
            img_bytes = buffered.getvalue()
            
            return base64.b64encode(img_bytes).decode("utf-8")
    
    def _build_prompt(self, nearby_pois: List[Dict], location_formatted: str) -> str:
        """
        Build structured prompt for vision LLM
        
        Args:
            nearby_pois: Array of POI objects with name, category, distance_m, source
            location_formatted: Human-readable location string
            
        Returns:
            JSON-formatted prompt string
        """
        # Format POI context for the LLM
        poi_context = ""
        if nearby_pois:
            poi_items = []
            for poi in nearby_pois[:10]:  # Limit to top 10
                name = poi.get('name', 'Unknown')
                category = poi.get('category', 'unknown')
                distance = poi.get('distance_m', 0)
                source = poi.get('source', 'unknown')
                poi_items.append(f"  - {name} ({category}, {distance}m away, source: {source})")
            poi_context = "\n".join(poi_items)
        
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
   - **Schema**: {{POI or landmark}}, {{city or region from GPS context}}
   - **MUST include geographic location** from GPS context - use the actual country/region/city provided
   - **Content**: Must reference the actual subject/POI from description and primary_subject (NOT incidental nearby retail POIs)
   - **Tone**: Factual and neutral - NO promotional adjectives (beautiful/amazing/iconic/stunning)
   - **Clarity**: Simple wording suitable for bottom-of-image overlay - no complex clauses, minimal punctuation
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
        
        return prompt
    
    def analyze_image(
        self, 
        image_path: str,
        nearby_pois: List[Dict],
        location_formatted: str,
        timeout: int = 30
    ) -> Optional[Dict]:
        """
        Analyze image with vision LLM
        
        Args:
            image_path: Path to image file
            nearby_pois: Array of POI objects from metadata
            location_formatted: Human-readable location string
            timeout: Request timeout in seconds
            
        Returns:
            Dict with llm_model, llm_analysis_time, description, primary_subject, watermark
            or None if analysis fails
        """
        try:
            start_time = time.time()
            
            # Encode image
            base64_image = self._encode_image_base64(image_path)
            
            # Build prompt
            prompt = self._build_prompt(nearby_pois, location_formatted)
            
            # Construct multi-modal payload
            payload = {
                "model": self.model,
                "prompt": prompt,
                "images": [base64_image],
                "stream": False,
                "options": {
                    "temperature": 0.5,
                    "top_p": 0.9
                }
            }
            
            # Send request to Ollama
            response = requests.post(
                self.generate_url,
                json=payload,
                timeout=timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                raw_response = result.get('response', '').strip()
                
                # Parse JSON response
                try:
                    # Extract JSON from response (might have markdown code blocks)
                    json_str = raw_response
                    if '```json' in json_str:
                        json_str = json_str.split('```json')[1].split('```')[0].strip()
                    elif '```' in json_str:
                        json_str = json_str.split('```')[1].split('```')[0].strip()
                    
                    # Try parsing with strict=False to allow control characters
                    try:
                        analysis_data = json.loads(json_str, strict=False)
                    except json.JSONDecodeError:
                        # If that fails, manually escape control characters in string values
                        # Replace unescaped newlines and tabs within JSON strings
                        import re
                        # Find all string values and escape control chars
                        def escape_controls(match):
                            s = match.group(0)
                            s = s.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
                            return s
                        # Apply to content between quotes (but preserve the quotes)
                        json_str = re.sub(r'": "([^"]*)"', lambda m: '": "' + m.group(1).replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t') + '"', json_str, flags=re.DOTALL)
                        analysis_data = json.loads(json_str)
                    
                    # Fill in timing
                    elapsed_time = time.time() - start_time
                    analysis_data['llm_analysis_time'] = round(elapsed_time, 2)
                    analysis_data['llm_model'] = self.model
                    
                    # Validate required fields
                    required_fields = ['description', 'primary_subject', 'watermark']
                    if not all(field in analysis_data for field in required_fields):
                        print(f"⚠️  Missing required fields in LLM response: {analysis_data.keys()}")
                        return None
                    
                    # Clean all string fields - strip leading/trailing whitespace and newlines
                    for field in required_fields:
                        if field in analysis_data and isinstance(analysis_data[field], str):
                            # Strip whitespace and newlines
                            cleaned = analysis_data[field].strip().lstrip('\n').strip()
                            # Strip common markdown formatting if present
                            import re
                            cleaned = re.sub(r'\*\*([^*]+)\*\*', r'\1', cleaned)  # **bold**
                            cleaned = re.sub(r'\*([^*]+)\*', r'\1', cleaned)      # *italic*
                            cleaned = re.sub(r'__([^_]+)__', r'\1', cleaned)      # __bold__
                            cleaned = re.sub(r'_([^_]+)_', r'\1', cleaned)        # _italic_
                            analysis_data[field] = cleaned
                    
                    # Truncate watermark if too long
                    watermark = analysis_data.get('watermark', '')
                    if len(watermark) > 100:
                        watermark = watermark[:97] + "..."
                        analysis_data['watermark'] = watermark
                    
                    return analysis_data
                    
                except json.JSONDecodeError as e:
                    print(f"⚠️  Failed to parse JSON from vision LLM: {e}")
                    print(f"    Raw response: {raw_response[:300]}")
                    return None
            else:
                print(f"⚠️  Vision LLM API error: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.Timeout:
            print(f"⚠️  Vision LLM request timeout after {timeout}s")
            return None
        except requests.exceptions.ConnectionError:
            print(f"⚠️  Cannot connect to Ollama at {self.endpoint}")
            return None
        except FileNotFoundError:
            print(f"⚠️  Image file not found: {image_path}")
            return None
        except Exception as e:
            print(f"⚠️  Vision LLM analysis error: {e}")
            return None
    
    def generate_fallback(
        self, 
        location_formatted: str,
        nearby_pois: List[Dict],
        date_taken: str = None
    ) -> Dict:
        """
        Generate fallback analysis without vision LLM
        
        Args:
            location_formatted: Human-readable location string
            nearby_pois: Array of POI objects
            date_taken: Optional date string
            
        Returns:
            Basic analysis dict with minimal data
        """
        # Extract first POI name if available
        poi_name = None
        poi_category = 'location'
        if nearby_pois and len(nearby_pois) > 0:
            poi_name = nearby_pois[0].get('name')
            poi_category = nearby_pois[0].get('category', 'location')
        
        # Build simple watermark
        watermark = location_formatted
        if poi_name:
            watermark = f"{poi_name}, {location_formatted}"
        
        return {
            'llm_model': 'fallback',
            'llm_analysis_time': 0.0,
            'description': f"Photo taken at {location_formatted}. Located near {poi_name}." if poi_name else f"Photo taken at {location_formatted}",
            'primary_subject': poi_name or location_formatted,
            'watermark': watermark[:100]
        }
