"""
LLM Image Analyzer
Analyzes images using gemma4:latest via Ollama
Generates terse JSON for two watermark lines
"""

import base64
import json
import time
import requests
from pathlib import Path
from PIL import Image
from typing import Any, Dict, Optional, List
from io import BytesIO


class LLMImageAnalyzer:
    """Analyze images with a terse factual watermark prompt."""
    
    def __init__(
        self,
        endpoint: str = "http://localhost:11434",
        model: str = "gemma4:latest",
        max_line1_words: int = 8,
        max_line2_words: int = 14,
    ):
        """
        Initialize LLM image analyzer
        
        Args:
            endpoint: Ollama API endpoint
            model: Vision model to use (gemma4:latest)
            max_line1_words: Maximum words allowed in returned line1 candidate
            max_line2_words: Maximum words allowed in returned line2 candidate
        """
        self.endpoint = endpoint.rstrip('/')
        self.model = model
        self.generate_url = f"{self.endpoint}/api/generate"
        self.max_line1_words = max(3, int(max_line1_words))
        self.max_line2_words = max(6, int(max_line2_words))
    
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
    
    def _build_prompt(
        self,
        cache_key: str,
        geo_entry: Dict[str, Any],
        nearby_pois: List[Dict],
        location: Dict,
        gps: Dict,
        poi_search: Dict,
        photo_name: str = "",
    ) -> str:
        """
        Build terse prompt for vision/text LLM
        
        Args:
            nearby_pois: Array of POI objects with name, category, distance_m, source
            location: Full location dict with city, state, country, display_name, etc.
            gps: GPS coordinates dict with lat, lon, altitude, heading
            poi_search: POI search metadata with attempted, radius, etc.
            
        Returns:
            JSON-formatted prompt string
        """
        # Extract GPS coordinates
        lat = gps.get('lat', 'unknown')
        lon = gps.get('lon', 'unknown')
        altitude = gps.get('altitude', 'unknown')
        heading = gps.get('heading', 'unknown')
        cardinal = gps.get('cardinal', '')
        
        # Extract location details
        city = location.get('city', '')
        state = location.get('state', '')
        country = location.get('country', '')
        display_name = location.get('display_name', '')
        road = location.get('road', '')
        location_formatted = location.get('formatted', 'Unknown Location')
        poi_found = location.get('poi_found', False)
        osm_type = location.get('osm_type', '')
        osm_category = location.get('category', '')
        osm_place_type = location.get('type', '')
        provider = location.get('provider', '')
        
        search_radius = poi_search.get('search_radius_m', 'unknown')
        fallback_context = poi_search.get('fallback_context') or {}
        fallback_anchor = str(fallback_context.get('anchor') or '').strip()
        fallback_summary = str(fallback_context.get('summary') or '').strip()
        fallback_type = str(fallback_context.get('type') or 'location').strip()
        fallback_formatted = str(
            fallback_context.get('formatted') or fallback_context.get('display_name') or location_formatted
        ).strip()
        
        poi_context = ""
        if nearby_pois:
            poi_items = []
            for poi in nearby_pois[:5]:
                name = poi.get('name', 'Unknown')
                category = poi.get('category', 'unknown')
                distance = poi.get('distance_m', 0)
                bearing = poi.get('bearing_cardinal', '')
                poi_items.append(f"  - {name} ({category}, {distance}m {bearing})")
            poi_context = "\n".join(poi_items)
        elif fallback_summary:
            poi_context = (
                f"  - Base location context: {fallback_summary} ({fallback_type})"
            )

        geo_payload = dict(geo_entry or {})
        geo_payload.pop('LLM_Watermark_Line1', None)
        geo_payload.pop('LLM_Watermark_Line2', None)
        geo_json = json.dumps(geo_payload, indent=2, ensure_ascii=False)
        
        prompt = f"""You MUST return valid JSON only. Do not include any text outside the JSON object.

You are a highly professional, objective content specialist writing terse factual watermark text.

Your task is to create exactly two short watermark lines for one geotagged photo entry.
The output must be efficient, factual, direct, and free of noise.

PHOTO:
    File Name: {photo_name or 'N/A'}

COORDINATE KEY:
    {cache_key}

GPS COORDINATES:
    Latitude: {lat}, Longitude: {lon}
    Altitude: {altitude}m, Heading: {heading}° {cardinal}

LOCATION:
  City: {city or 'N/A'}
  State/Region: {state or 'N/A'}
  Country: {country or 'N/A'}
  Road: {road or 'N/A'}
  Display Name: {display_name or 'N/A'}

GEOCODING (from {provider}):
  OSM Type: {osm_type or 'N/A'}, Category: {osm_category or 'N/A'}, Place Type: {osm_place_type or 'N/A'}
  POI at exact location: {'Yes' if poi_found else 'No'}

BASE LOCATION CONTEXT:
    Anchor: {fallback_anchor or 'N/A'}
    Summary: {fallback_summary or 'N/A'}
    Type: {fallback_type or 'N/A'}
    Area: {fallback_formatted or 'N/A'}

NEARBY POINTS OF INTEREST ({len(nearby_pois)} within {search_radius}m):
{poi_context if poi_context else "  None found"}

FULL GEO ENTRY JSON:
{geo_json}

TASK:
Return ONLY valid JSON with these fields:
- LLM_Watermark_Line1: no more than {self.max_line1_words} words
- LLM_Watermark_Line2: no more than {self.max_line2_words} words

RULES:
- Output must be exactly two short factual lines expressed as JSON values
- No paragraph, no explanation, no options, no extra keys
- No promotional adjectives, no mood words, no cinematic language
- LINE 1 must summarize the immediate physical reality or situational context
- LINE 1 must not mention the city name unless unavoidable
- LINE 1 should prefer road, trail, park, area, or nearest grounded POI context
- LINE 2 must be a deterministic location stamp grounded only in provided metadata
- LINE 2 format target: [Specific street/area if important] | [City], [State/Province], [Country]
- If the street or area is weak, omit it and use the strongest deterministic location stamp
- If nearby POIs are empty, use BASE LOCATION CONTEXT only as grounding; do not invent POIs
- Reuse exact names from metadata when possible
- If uncertain, leave the value empty rather than inventing text

OUTPUT FORMAT:
{{
  "llm_model": "{self.model}",
  "llm_analysis_time": 0.0,
    "LLM_Watermark_Line1": "",
    "LLM_Watermark_Line2": ""
}}"""
        
        return prompt
    
    def analyze_image(
        self,
        image_path: Optional[str],
        cache_key: str,
        geo_entry: Dict[str, Any],
        nearby_pois: List[Dict],
        location: Dict,
        gps: Dict,
        poi_search: Dict,
        photo_name: str = "",
        timeout: int = 30,
        debug_output_path: Optional[str] = None
    ) -> Optional[Dict]:
        """
        Analyze image with vision LLM
        
        Args:
            image_path: Path to image file
            nearby_pois: Array of POI objects from metadata
            location: Full location dict with city, state, country, etc.
            gps: GPS coordinates dict with lat, lon, altitude, heading
            poi_search: POI search metadata dict
            timeout: Request timeout in seconds
            debug_output_path: If provided, save prompt request to this JSON file
            
        Returns:
            Dict with llm_model, llm_analysis_time, LLM_Watermark_Line1, LLM_Watermark_Line2
            or None if analysis fails
        """
        try:
            start_time = time.time()
            
            # Build prompt
            prompt = self._build_prompt(
                cache_key=cache_key,
                geo_entry=geo_entry,
                nearby_pois=nearby_pois,
                location=location,
                gps=gps,
                poi_search=poi_search,
                photo_name=photo_name,
            )
            
            payload: Dict[str, Any] = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "top_p": 0.7,
                }
            }
            if image_path:
                payload["images"] = [self._encode_image_base64(image_path)]

            payload = {
                **payload
            }
            
            # DEBUG: Save prompt request to file if path provided
            if debug_output_path:
                debug_data = {
                    "image_path": image_path,
                    "cache_key": cache_key,
                    "photo_name": photo_name,
                    "model": self.model,
                    "endpoint": self.generate_url,
                    "gps": gps,
                    "geo_entry": geo_entry,
                    "location": location,
                    "poi_search": poi_search,
                    "nearby_pois": nearby_pois,
                    "payload": {
                        "model": payload["model"],
                        "prompt": payload["prompt"],
                        "stream": payload["stream"],
                        "options": payload["options"],
                        "images": ["<base64_encoded_image>"]
                    }
                }
                
                # Load existing debug file or create new structure
                debug_path = Path(debug_output_path)
                debug_path.parent.mkdir(parents=True, exist_ok=True)
                
                if debug_path.exists():
                    with open(debug_path, 'r', encoding='utf-8') as f:
                        all_prompts = json.load(f)
                else:
                    all_prompts = {}
                
                # Use image filename as key
                image_key = Path(image_path).name
                all_prompts[image_key] = debug_data
                
                # Write back to file
                with open(debug_path, 'w', encoding='utf-8') as f:
                    json.dump(all_prompts, f, indent=2, ensure_ascii=False)
                
                print(f"🐛 Debug: Added {image_key} to {debug_path}")
            
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
                    
                    required_fields = ['LLM_Watermark_Line1', 'LLM_Watermark_Line2']
                    if not all(field in analysis_data for field in required_fields):
                        print(f"⚠️  Missing required fields in LLM response: {analysis_data.keys()}")
                        return None
                    
                    for field in required_fields:
                        if field in analysis_data and isinstance(analysis_data[field], str):
                            cleaned = analysis_data[field].strip().lstrip('\n').strip()
                            import re
                            cleaned = re.sub(r'\*\*([^*]+)\*\*', r'\1', cleaned)
                            cleaned = re.sub(r'\*([^*]+)\*', r'\1', cleaned)
                            cleaned = re.sub(r'__([^_]+)__', r'\1', cleaned)
                            cleaned = re.sub(r'_([^_]+)_', r'\1', cleaned)
                            cleaned = " ".join(cleaned.split())
                            analysis_data[field] = cleaned

                    line1_words = analysis_data.get('LLM_Watermark_Line1', '').split()
                    line2_words = analysis_data.get('LLM_Watermark_Line2', '').split()
                    analysis_data['LLM_Watermark_Line1'] = " ".join(line1_words[: self.max_line1_words])[:100]
                    analysis_data['LLM_Watermark_Line2'] = " ".join(line2_words[: self.max_line2_words])[:140]
                    
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
        poi_search: Optional[Dict] = None,
        geo_entry: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        """
        Generate fallback analysis without vision LLM
        
        Args:
            location_formatted: Human-readable location string
            nearby_pois: Array of POI objects
            poi_search: Optional POI search metadata including fallback_context
            geo_entry: Optional raw geocode cache entry
            
        Returns:
            Basic analysis dict with minimal data
        """
        poi_name = None
        anchor = None
        if nearby_pois and len(nearby_pois) > 0:
            poi_name = nearby_pois[0].get('name')
        else:
            fallback_context = (poi_search or {}).get('fallback_context') or {}
            anchor = fallback_context.get('anchor') or fallback_context.get('summary')
            poi_name = anchor

        geo_entry = geo_entry or {}
        road = str(geo_entry.get('road') or '').strip()
        city = str(geo_entry.get('city') or '').strip()
        state = str(geo_entry.get('state') or '').strip()
        country = str(geo_entry.get('country') or '').strip()

        line1_value = road or poi_name or location_formatted or 'Unknown Place'
        line2_parts = []
        if road and city:
            line2_parts.append(road)
        locality = ', '.join([part for part in [city, state, country] if part])
        if locality:
            line2_parts.append(locality)
        line2_value = ' | '.join(line2_parts) if line2_parts else location_formatted

        line1_value = " ".join(str(line1_value).split()[: self.max_line1_words])[:100]
        line2_value = " ".join(str(line2_value).split()[: self.max_line2_words])[:140]
        
        return {
            'llm_model': 'fallback',
            'llm_analysis_time': 0.0,
            'LLM_Watermark_Line1': line1_value,
            'LLM_Watermark_Line2': line2_value,
        }
