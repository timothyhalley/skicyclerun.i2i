"""
Ollama Watermark Generator
Generates enhanced watermark text using Ollama LLM based on photo metadata
"""

import requests
import json
from typing import Dict, Optional
from datetime import datetime


class OllamaWatermarkGenerator:
    """Generate enhanced watermarks using Ollama"""
    
    def __init__(self, endpoint: str = "http://localhost:11434", model: str = "llama3.2:3b"):
        """
        Initialize Ollama watermark generator
        
        Args:
            endpoint: Ollama API endpoint
            model: Model to use for generation
        """
        self.endpoint = endpoint.rstrip('/')
        self.model = model
        self.generate_url = f"{self.endpoint}/api/generate"
    
    def _build_prompt(self, metadata: Dict) -> str:
        """Build prompt for Ollama based on metadata"""
        
        # Extract key metadata
        location = metadata.get('location_formatted', 'Unknown Location')
        poi_name = None
        if metadata.get('location', {}).get('poi_found'):
            poi_name = metadata.get('location', {}).get('name')
        
        # DO NOT include date or camera in prompt - LLM will use them even if told not to
        landmarks = metadata.get('landmarks', [])
        
        # Extract GPS coordinates for context
        gps = metadata.get('gps', {})
        lat = gps.get('lat')
        lon = gps.get('lon')
        
        # Build context for prompt
        context_parts = [f"Location: {location}"]
        if lat and lon:
            context_parts.append(f"GPS Coordinates: {lat:.6f}, {lon:.6f}")
        if poi_name:
            poi_type = metadata.get('location', {}).get('type', 'unknown')
            context_parts.append(f"Point of Interest: {poi_name} (type: {poi_type})")
        if landmarks:
            # Include distance info for better LLM prioritization
            landmark_details = []
            for l in landmarks[:3]:  # Include top 3 landmarks
                if l.get('name'):
                    dist = l.get('distance_m', 0)
                    category = l.get('category', 'landmark')
                    if dist < 1000:
                        landmark_details.append(f"{l['name']} ({int(dist)}m, {category})")
                    else:
                        landmark_details.append(f"{l['name']} ({dist/1000:.1f}km, {category})")
            if landmark_details:
                context_parts.append(f"Nearby landmarks: {', '.join(landmark_details)}")
        
        context = "\n".join(context_parts)
        
        prompt = f"""Using the provided GPS coordinates and location information, create structured location data for this photo.

{context}

PRIORITY ORDER (use highest quality option available):
1. Geographic landmarks (mountains, rivers, lakes, parks, natural features)
2. Cultural landmarks (temples, monuments, historic buildings, museums)
3. Named venues (restaurants, theaters, unique establishments)
4. City/neighborhood (if no specific landmark)

REJECT low-quality POIs:
- Chain stores (7-Eleven, Starbucks, McDonald's, gas stations)
- Generic businesses (convenience stores, ATMs, parking)
- If POI is low-quality, use nearby landmark from the list above instead

STRICT RULES:
- Use ONLY actual location names, POI names, and landmarks provided above
- NO invented wording, creative prose, or promotional language
- NO numbers (dates, years, street numbers, postal codes)
- NO emojis or special Unicode characters
- Be factual and neutral

Return ONLY valid JSON with this exact structure:
{{
  "location_name": "",       
  "poi_type": "",            
  "description": "",         
  "summary_sentence": "",    
  "highlight": "",           
  "watermark": ""            
}}

Field requirements:
- location_name: Exact POI or location name from data above
- poi_type: Type of POI (temple, park, museum, restaurant, neighborhood, etc.)
- description: 2-3 sentence factual description of location's significance
- summary_sentence: One sentence highlighting key points
- highlight: Concise factual summation
- watermark: ≤10 words, plain text, format [Landmark/POI], [City/Area]

JSON output:"""
        
        return prompt
    
    def generate_watermark(self, metadata: Dict, timeout: int = 10) -> Optional[Dict]:
        """
        Generate enhanced watermark and location enrichment using Ollama
        
        Args:
            metadata: Photo metadata dictionary
            timeout: Request timeout in seconds
            
        Returns:
            Dict with 'watermark' string and optional 'enhanced_data' dict containing
            full LLM response (location_name, poi_type, description, etc), or None if generation fails
        """
        try:
            prompt = self._build_prompt(metadata)
            
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "top_p": 0.9,
                    "max_tokens": 30
                }
            }
            
            response = requests.post(
                self.generate_url,
                json=payload,
                timeout=timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                raw_response = result.get('response', '').strip()
                
                # Parse JSON response
                enhanced_data = None
                watermark_text = None
                try:
                    # Extract JSON from response (might have markdown code blocks)
                    json_str = raw_response
                    if '```json' in json_str:
                        json_str = json_str.split('```json')[1].split('```')[0].strip()
                    elif '```' in json_str:
                        json_str = json_str.split('```')[1].split('```')[0].strip()
                    
                    enhanced_data = json.loads(json_str)
                    watermark_text = enhanced_data.get('watermark', '').strip()
                except json.JSONDecodeError as e:
                    print(f"⚠️  Failed to parse JSON from Ollama: {e}")
                    print(f"    Raw response: {raw_response[:200]}")
                    return None
                
                # ANTI-HALLUCINATION: Validate that generated text uses actual location/POI data
                location = metadata.get('location_formatted', '')
                poi_name = metadata.get('location', {}).get('name', '') if metadata.get('location', {}).get('poi_found') else ''
                
                # Extract specific geographic terms that MUST appear in output
                validation_terms = set()
                
                # Add POI name parts (highest priority)
                if poi_name:
                    poi_parts = [p.strip() for p in poi_name.replace(',', ' ').split()]
                    validation_terms.update([p.lower() for p in poi_parts if len(p) > 3 and not p.isdigit()])
                
                # Add location parts (city, area names)
                if location:
                    location_parts = [p.strip() for p in location.replace(',', ' ').split()]
                    # Filter out generic words
                    generic_words = {'drive', 'street', 'road', 'avenue', 'lane', 'way', 'place', 'canada', 'region', 'district'}
                    validation_terms.update([p.lower() for p in location_parts 
                                           if len(p) > 3 and not p.isdigit() and p.lower() not in generic_words])
                
                # Add landmarks if present
                landmarks = metadata.get('landmarks', [])
                for landmark in landmarks[:2]:
                    if landmark.get('name'):
                        parts = [p.strip() for p in landmark['name'].replace(',', ' ').split()]
                        validation_terms.update([p.lower() for p in parts if len(p) > 4])
                
                # Check if generated text contains actual geographic terms (not creative fluff)
                watermark_lower = watermark_text.lower()
                
                # Reject if it contains creative fluff words instead of location data
                fluff_words = {'charm', 'delight', 'wander', 'adventure', 'journey', 'explore', 
                             'beauty', 'moment', 'memory', 'escape', 'vibes', 'scene', 'views'}
                has_fluff = any(fluff in watermark_lower for fluff in fluff_words)
                
                # Must contain at least one actual location term
                has_valid_location = any(term in watermark_lower for term in validation_terms)
                
                if has_fluff or not has_valid_location:
                    print(f"⚠️  Ollama generated creative fluff instead of location - rejecting: '{watermark_text}'")
                    print(f"    Expected terms: {list(validation_terms)[:5]}")
                    return None  # Force fallback
                
                # Truncate watermark if too long
                if len(watermark_text) > 100:
                    watermark_text = watermark_text[:97] + "..."
                
                # Return dict with watermark and full enhanced data
                result_dict = {'watermark': watermark_text}
                if enhanced_data:
                    result_dict['enhanced_data'] = enhanced_data
                
                return result_dict if watermark_text else None
            else:
                print(f"⚠️  Ollama API error: {response.status_code} - {response.text}")
                return None
                
        except requests.exceptions.Timeout:
            print(f"⚠️  Ollama request timeout after {timeout}s")
            return None
        except requests.exceptions.ConnectionError:
            print(f"⚠️  Cannot connect to Ollama at {self.endpoint}")
            return None
        except Exception as e:
            print(f"⚠️  Ollama generation error: {e}")
            return None
    
    def generate_fallback(self, metadata: Dict) -> str:
        """
        Generate simple fallback watermark without Ollama
        
        Args:
            metadata: Photo metadata dictionary
            
        Returns:
            Simple watermark text
        """
        location = metadata.get('location_formatted', 'Unknown Location')
        
        # Try to get year from date_taken
        date_taken = metadata.get('date_taken', '')
        year = ''
        if date_taken:
            try:
                dt = datetime.fromisoformat(date_taken.replace('Z', '+00:00'))
                year = f" • {dt.year}"
            except:
                pass
        
        # Check for POI name
        poi_name = None
        if metadata.get('location', {}).get('poi_found'):
            poi_name = metadata.get('location', {}).get('name')
        
        if poi_name:
            return f"{poi_name}, {location}{year}"
        else:
            return f"{location}{year}"
