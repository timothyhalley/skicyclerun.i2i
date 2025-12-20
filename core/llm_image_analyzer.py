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
    
    def _build_prompt(self, nearby_pois: List[Dict], location: Dict, gps: Dict, poi_search: Dict) -> str:
        """
        Build structured prompt for vision LLM
        
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
        
        # Extract POI search metadata
        poi_attempted = poi_search.get('attempted', False)
        search_radius = poi_search.get('search_radius_m', 'unknown')
        max_distance = poi_search.get('max_distance_m', 'unknown')
        heading_filter = poi_search.get('heading_filter_used', False)
        
        # Format POI context for the LLM
        poi_context = ""
        if nearby_pois:
            poi_items = []
            for poi in nearby_pois[:10]:  # Limit to top 10
                name = poi.get('name', 'Unknown')
                category = poi.get('category', 'unknown')
                distance = poi.get('distance_m', 0)
                bearing = poi.get('bearing_cardinal', '')
                source = poi.get('source', 'unknown')
                poi_items.append(f"  - {name} ({category}, {distance}m {bearing}, source: {source})")
            poi_context = "\n".join(poi_items)
        
        prompt = f"""You MUST return valid JSON only. Do not include any text outside the JSON object.

You are analyzing a photograph with the following metadata:

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

NEARBY POINTS OF INTEREST ({len(nearby_pois)} within {search_radius}m):
{poi_context if poi_context else "  None found"}

TASK:
Return ONLY valid JSON with these fields:
- description: 5-10 factual sentences about the subject, using city/country context
- primary_subject: 2-6 word phrase naming the main subject
- watermark_line1: A catchy, direct phrase describing the key subject/scene (10 words max)
- watermark_line2: City, State (we will add copyright programmatically)

RULES:
- No promotional adjectives
- No photo references
- watermark_line1: Focus on WHAT you see (subject/scene), NOT location
- watermark_line2: Just extract city and state from GPS data above
- If uncertain, leave fields empty

OUTPUT FORMAT:
{{
  "llm_model": "{self.model}",
  "llm_analysis_time": 0.0,
  "description": "",
  "primary_subject": "",
  "watermark_line1": "",
  "watermark_line2": ""
}}"""
        
        return prompt
    
    def analyze_image(
        self, 
        image_path: str,
        nearby_pois: List[Dict],
        location: Dict,
        gps: Dict,
        poi_search: Dict,
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
            Dict with llm_model, llm_analysis_time, description, primary_subject, watermark
            or None if analysis fails
        """
        try:
            start_time = time.time()
            
            # Encode image
            base64_image = self._encode_image_base64(image_path)
            
            # Build prompt
            prompt = self._build_prompt(nearby_pois, location, gps, poi_search)
            
            # Construct multi-modal payload
            payload = {
                "model": self.model,
                "prompt": prompt,
                "images": [base64_image],
                "stream": False,
                "options": {
                    "temperature": 0.2,  # Lower for more deterministic results
                    "top_p": 0.8         # Fewer rare tokens for consistency
                }
            }
            
            # DEBUG: Save prompt request to file if path provided
            if debug_output_path:
                debug_data = {
                    "image_path": image_path,
                    "model": self.model,
                    "endpoint": self.generate_url,
                    "gps": gps,
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
                    
                    # Validate required fields
                    required_fields = ['description', 'primary_subject', 'watermark_line1', 'watermark_line2']
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
                    
                    # Truncate watermark_line1 if too long
                    watermark_line1 = analysis_data.get('watermark_line1', '')
                    if len(watermark_line1) > 100:
                        watermark_line1 = watermark_line1[:97] + "..."
                        analysis_data['watermark_line1'] = watermark_line1
                    
                    # Truncate watermark_line2 if too long
                    watermark_line2 = analysis_data.get('watermark_line2', '')
                    if len(watermark_line2) > 100:
                        watermark_line2 = watermark_line2[:97] + "..."
                        analysis_data['watermark_line2'] = watermark_line2
                    
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
        
        # Build simple watermarks
        watermark_line1 = poi_name or 'Unknown Subject'
        watermark_line2 = location_formatted
        
        return {
            'llm_model': 'fallback',
            'llm_analysis_time': 0.0,
            'description': f"Photo taken at {location_formatted}. Located near {poi_name}." if poi_name else f"Photo taken at {location_formatted}",
            'primary_subject': poi_name or location_formatted,
            'watermark_line1': watermark_line1[:100],
            'watermark_line2': watermark_line2[:100]
        }
