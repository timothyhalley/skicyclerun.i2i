"""
Ollama-powered Location Display Name Enhancer

Uses local Ollama LLM to intelligently format location names and extract
points of interest (POI) and historical context for watermarking.
"""
import json
import requests
from typing import Dict, Optional, List
from pathlib import Path


class OllamaLocationEnhancer:
    def __init__(self, config: Dict, model: str = "llama3.2:latest", host: str = "http://localhost:11434"):
        self.config = config
        self.model = model
        self.host = host
        self.api_url = f"{host}/api/generate"
        
    def enhance_location(self, location_info: Dict) -> Dict:
        """
        Enhance location with AI-generated display name and context.
        
        Args:
            location_info: Raw location dict from geocoding with display_name, address, etc.
            
        Returns:
            Dict with:
                - file: Image file path
                - display_name: Original display_name from geocoding
                - poi: Notable landmarks (comma-separated)
                - history: Brief historical context
                - basic_watermark: Simple "City, State" format
                - enhanced_watermark: Rich "City: Landmark - Context" format
        """
        if not location_info:
            return {
                'display_name': '',
                'poi': '',
                'history': '',
                'basic_watermark': 'Unknown Location',
                'enhanced_watermark': 'Unknown Location'
            }
        
        # Extract components
        display_name = location_info.get('display_name', '')
        address = location_info.get('address', {})
        namedetails = location_info.get('namedetails', {})
        
        # Build context for LLM
        context = self._build_context(display_name, address, namedetails)
        
        # Call Ollama
        prompt = self._build_prompt(context)
        
        try:
            response = self._call_ollama(prompt)
            llm_data = self._parse_response(response)
            
            # Extract watermarks directly from LLM (already contextual and flowing)
            watermark = llm_data.get('watermark_text', '')
            watermark_en = llm_data.get('watermark_text_en', watermark)
            
            if not watermark or watermark == 'Unknown Location':
                # Fallback: extract from display_name
                parts = [p.strip() for p in display_name.split(',')]
                if len(parts) >= 2:
                    watermark = f"{parts[1]}, {parts[-1]}"  # City, Country
                    watermark_en = watermark
                else:
                    watermark = self._basic_format(address)
                    watermark_en = watermark
            
            poi = llm_data.get('notable_poi', '')
            poi_en = llm_data.get('notable_poi_en', poi)
            history = llm_data.get('brief_history', '')
            
            # Format bilingual display
            if watermark != watermark_en:
                bilingual = f"{watermark} ({watermark_en})"
            else:
                bilingual = watermark
            
            return {
                'display_name': display_name,
                'display_name_en': watermark_en,
                'poi': poi,
                'poi_en': poi_en,
                'history': history,
                'basic_watermark': watermark,
                'basic_watermark_en': watermark_en,
                'enhanced_watermark': bilingual,
                'enhanced_watermark_original': watermark,
                'enhanced_watermark_english': watermark_en
            }
        except Exception as e:
            print(f"⚠️  Ollama failed: {e}")
            # Fallback
            parts = [p.strip() for p in display_name.split(',')]
            basic = f"{parts[1]}, {parts[-1]}" if len(parts) >= 2 else self._basic_format(address)
            return {
                'display_name': display_name,
                'poi': '',
                'history': '',
                'basic_watermark': basic,
                'enhanced_watermark': basic
            }
    
    def _build_context(self, display_name: str, address: Dict, namedetails: Dict) -> Dict:
        """Build structured context for LLM."""
        return {
            'display_name': display_name,
            'road': address.get('road', ''),
            'suburb': address.get('suburb', ''),
            'city': address.get('city', ''),
            'town': address.get('town', ''),
            'village': address.get('village', ''),
            'county': address.get('county', ''),
            'state': address.get('state', ''),
            'country': address.get('country', ''),
            'country_code': address.get('country_code', '').upper(),
            'postcode': address.get('postcode', ''),
            'english_name': namedetails.get('name:en', ''),
            'local_name': namedetails.get('name', '')
        }
    
    def _build_prompt(self, context: Dict) -> str:
        """Build prompt for Ollama."""
        return f"""You are a location naming expert for photo watermarks. Analyze the location data and respond with ONLY valid JSON.

INPUT LOCATION DATA:
Display Name: {context['display_name']}
English Name: {context['english_name']}
Road: {context['road']}
Neighborhood: {context['suburb']}
City: {context['city']}
Town: {context['town']}
State/Province: {context['state']}
Country: {context['country']}

TASK 1 - Analyze and list notable_poi:
- Identify 2-3 most significant landmarks, parks, or attractions at this location
- Research what makes this location special or recognizable
- Use comma-separated format: "Landmark A, Landmark B, Landmark C"
- For English locations, use ONLY English (never translate to other languages!)
- For non-English locations (Japan, China, Korea), preserve original characters
- Examples:
  * New York: "Washington Square Park, NYU Campus, Greenwich Village"
  * Tokyo: "明治神宮, 代々木公園, 原宿"
  * Barcelona: "Sagrada Familia, Casa Batllo, Park Guell"
- If no notable POI, use empty string ""

TASK 2 - List notable_poi_en (ENGLISH TRANSLATION if needed):
- If Task 1 POIs are in non-English language, translate them here
- If Task 1 POIs are ALREADY in English, use EXACT SAME VALUE (no translation!)
- Never translate English names to other languages
- Comma-separated format matching Task 1
- Examples:
  * English already: "Washington Square Park, NYU Campus" → same
  * Japanese: "明治神宮, 代々木公園" → "Meiji Shrine, Yoyogi Park"

TASK 3 - Provide brief_history:
- One sentence (max 120 characters) explaining what makes location significant
- Describe the MOST IMPORTANT landmark or feature first
- Explain relationships between POIs (e.g., "Park anchors neighborhood, adjacent to university")
- Focus on the PRIMARY attraction that defines this place
- Use English regardless of location language
- Examples:
  * "Historic Washington Square Park anchors Greenwich Village, home to NYU campus"
  * "Iconic Meiji Shrine sits in Yoyogi Park, adjacent to vibrant Harajuku district"
  * "Brooklyn Bridge connects Manhattan to DUMBO waterfront neighborhood"

TASK 4 - Create watermark_text (ORIGINAL LANGUAGE):
- NOW synthesize the perfect watermark from your analysis above
- Include ALL significant POIs from your analysis (2-3 landmarks)
- Connect with natural words: "at", "in", "and", "near", "with"
- Format: 6-10 words, flowing and contextual
- DO NOT include country names (US, United States, America, Japan, etc.)
- DO NOT include city names (New York, Brooklyn, Tokyo, Barcelona, etc.) - city goes on copyright line
- Focus ONLY on landmarks, parks, buildings, districts, neighborhoods, rivers, bays
- For English locations, use ONLY English (never add foreign characters!)
- For non-English locations, preserve original language
- Prioritize architectural/cultural landmarks over generic references
- Examples:
  * "Jefferson Market Library and Washington Square Park near NYU" (landmarks only, no "New York")
  * "Prospect Park and Public Library near Grand Army Plaza" (landmarks only, no "Brooklyn")
  * "Brooklyn Bridge and DUMBO Waterfront at East River" (no "Manhattan" or "NYC")
  * "明治神宮と代々木公園、原宿渋谷" (Japanese preserved, districts but no "Tokyo")
  * "Sagrada Familia and Park Guell, Gothic Quarter" (landmarks only, no "Barcelona")

TASK 5 - Create watermark_text_en (ENGLISH TRANSLATION):
- English version of watermark with same flowing style
- If Task 4 is already English, use EXACT SAME VALUE
- If Task 4 is non-English, translate maintaining same structure
- 6-10 words max, natural phrasing

CRITICAL LANGUAGE RULES:
- For locations in English-speaking countries (US, UK, Canada, Australia), use ONLY English
- NEVER translate English locations to Japanese, Korean, Chinese, or other languages
- Only use non-English when the location itself is in a non-English country
- Double-check: If input shows "United States", "New York", "Brooklyn" → output must be 100% English

CRITICAL: Output MUST be valid JSON with proper field names (use underscores, not escaped underscores)
Field names are: notable_poi, notable_poi_en, brief_history, watermark_text, watermark_text_en
Order matters: analyze POIs first, then history, then synthesize watermark

REQUIRED JSON OUTPUT FORMAT (respond with ONLY this, no other text):
{{
    "notable_poi": "Most important landmarks at this location (original language)",
    "notable_poi_en": "English translation if needed, else SAME as notable_poi",
    "brief_history": "Key significance - PRIMARY landmark first, relationships explained",
    "watermark_text": "5-8 word watermark synthesized from analysis above",
    "watermark_text_en": "English version, or SAME if already English"
}}

EXAMPLE OUTPUTS (showing analysis → synthesis flow):

Input: Road=University Place, Neighborhood=Greenwich Village, City=New York, State=New York, Country=United States
Output: {{
    "notable_poi": "Jefferson Market Library, Washington Square Park, New York University",
    "notable_poi_en": "Jefferson Market Library, Washington Square Park, New York University",
    "brief_history": "Historic Jefferson Market Library and Washington Square Park anchor Greenwich Village near NYU campus",
    "watermark_text": "Jefferson Market Library and Washington Square Park near NYU",
    "watermark_text_en": "Jefferson Market Library and Washington Square Park near NYU"
}}

Input: Neighborhood=Prospect Park, City=Brooklyn, County=Kings County, State=New York, Country=United States
Output: {{
    "notable_poi": "Prospect Park, Brooklyn Public Library, Grand Army Plaza, East River",
    "notable_poi_en": "Prospect Park, Brooklyn Public Library, Grand Army Plaza, East River",
    "brief_history": "Historic Prospect Park and Public Library anchor neighborhood near Grand Army Plaza and East River",
    "watermark_text": "Prospect Park and Public Library near Grand Army Plaza and East River",
    "watermark_text_en": "Prospect Park and Public Library near Grand Army Plaza and East River"
}}

Input: Neighborhood=DUMBO, City=Brooklyn, County=Kings County, State=New York, Country=United States
Output: {{
    "notable_poi": "Brooklyn Bridge, DUMBO Waterfront, East River, Manhattan Bridge",
    "notable_poi_en": "Brooklyn Bridge, DUMBO Waterfront, East River, Manhattan Bridge",
    "brief_history": "Iconic Brooklyn Bridge connects to DUMBO waterfront neighborhood along East River",
    "watermark_text": "Brooklyn Bridge and DUMBO Waterfront at East River",
    "watermark_text_en": "Brooklyn Bridge and DUMBO Waterfront at East River"
}}

Input: Road=Carrer de Provença, Neighborhood=la Sagrada Familia, City=Barcelona, State=Catalunya, Country=España
Output: {{
    "notable_poi": "Sagrada Familia, Casa Batllo, Park Guell, Gothic Quarter",
    "notable_poi_en": "Sagrada Familia, Casa Batllo, Park Guell, Gothic Quarter",
    "brief_history": "Gaudi's iconic Sagrada Familia and Casa Batllo showcase modernist architecture in Gothic Quarter",
    "watermark_text": "Sagrada Familia and Casa Batllo, Gaudi's Gothic Quarter",
    "watermark_text_en": "Sagrada Familia and Casa Batllo, Gaudi's Gothic Quarter"
}}

Input: Neighborhood=Marina Bay, City=Singapore, Country=Singapore
Output: {{
    "watermark_text": "Marina Bay Sands and Gardens, Singapore",
    "watermark_text_en": "Marina Bay Sands and Gardens, Singapore",
    "notable_poi": "Marina Bay Sands, Gardens by the Bay, Merlion",
    "notable_poi_en": "Marina Bay Sands, Gardens by the Bay, Merlion",
    "brief_history": "Iconic waterfront with hotel, gardens and bay attractions"
}}

Input: Road=海岸一丁目, Neighborhood=海岸, City=港区, State=東京都, Postcode=104-0046, Country=日本
Output: {{
    "watermark_text": "芝浦ふ頭海浜公園、東京湾沿岸港区",
    "watermark_text_en": "Shibaura Seaside Park, Tokyo Bay Waterfront",
    "notable_poi": "芝浦ふ頭海浜公園, 東京湾",
    "notable_poi_en": "Shibaura Pier Seaside Park, Tokyo Bay",
    "brief_history": "Coastal park sits along Tokyo Bay waterfront in Minato Ward"
}}

Input: Road=明治通り, Neighborhood=渋谷, City=渋谷区, State=東京都, Country=日本
Output: {{
    "notable_poi": "明治神宮, 代々木公園, 原宿, 渋谷",
    "notable_poi_en": "Meiji Shrine, Yoyogi Park, Harajuku, Shibuya",
    "brief_history": "Historic Meiji Shrine sits within Yoyogi Park, adjacent to vibrant Harajuku and Shibuya districts",
    "watermark_text": "明治神宮と代々木公園、原宿渋谷",
    "watermark_text_en": "Meiji Shrine and Yoyogi Park, Harajuku Shibuya"
}}

IMPORTANT GUIDELINES FOR NON-ENGLISH LOCATIONS:
- For Japanese addresses, identify the actual area meaning and nearby features
  Example: 海岸 = "coast/seaside", 港区 = "Minato Ward", 芝浦 = "Shibaura district"
- Research contextual POIs even if not explicitly in address
  Example: Shibaura coastline → nearby Shibaura Pier Park, Tokyo Bay views
- Create meaningful watermarks that tell a story about the location
- Use proper romanization and translations (not just phonetic)
- Preserve cultural significance in both original and English versions

NOW PROCESS THIS LOCATION - RESPOND WITH ONLY JSON:"""

    def _call_ollama(self, prompt: str, temperature: float = 0.3) -> str:
        """Call Ollama API with streaming disabled for JSON response."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "temperature": temperature,
            "format": "json"  # Request JSON format
        }
        
        response = requests.post(self.api_url, json=payload, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        return result.get('response', '')
    
    def _parse_response(self, response: str) -> Dict:
        """Parse Ollama JSON response with strict field mapping."""
        # Sanitize response - remove escaped underscores that LLM might add
        response = response.replace('\\_', '_')
        
        try:
            data = json.loads(response)
            return {
                'watermark_text': data.get('watermark_text', 'Unknown Location'),
                'watermark_text_en': data.get('watermark_text_en', data.get('watermark_text', 'Unknown Location')),
                'notable_poi': data.get('notable_poi', ''),
                'notable_poi_en': data.get('notable_poi_en', data.get('notable_poi', '')),
                'brief_history': data.get('brief_history', '')
            }
        except json.JSONDecodeError:
            # Try to extract JSON from response if wrapped in text
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                data = json.loads(json_str)
                return {
                    'watermark_text': data.get('watermark_text', 'Unknown Location'),
                    'watermark_text_en': data.get('watermark_text_en', data.get('watermark_text', 'Unknown Location')),
                    'notable_poi': data.get('notable_poi', ''),
                    'notable_poi_en': data.get('notable_poi_en', data.get('notable_poi', '')),
                    'brief_history': data.get('brief_history', '')
                }
            raise
    
    def _basic_format(self, address: Dict) -> str:
        """Fallback basic formatting if Ollama fails."""
        parts = []
        
        city = address.get('city') or address.get('town') or address.get('village')
        if city:
            parts.append(city)
        
        state = address.get('state')
        if state:
            parts.append(state)
        
        country = address.get('country')
        if country:
            parts.append(country)
        
        return ', '.join(parts) if parts else 'Unknown Location'
    
    def _create_enhanced_watermark(self, basic: str, basic_en: str, poi: str, poi_en: str, history: str) -> Dict[str, str]:
        """
        Create enhanced watermarks in both original and English languages.
        
        Args:
            basic: Basic watermark (original language)
            basic_en: Basic watermark (English)
            poi: POI list (original language)
            poi_en: POI list (English)
            history: Historical context
            
        Returns:
            Dict with 'original', 'english', and 'bilingual' watermarks
        """
        def create_single_watermark(basic_text: str, poi_text: str) -> str:
            """Helper to create watermark for one language."""
            # If no POI, return basic
            if not poi_text:
                return basic_text
            
            # Check if basic already has landmark (contains colon)
            if ':' in basic_text:
                city_part = basic_text.split(':')[0].strip()
                landmark_part = basic_text.split(':')[1].strip()
                
                if poi_text:
                    poi_list = [p.strip() for p in poi_text.split(',')]
                    # If landmark already in POI, combine multiple POIs
                    if landmark_part in poi_text:
                        if len(poi_list) >= 2:
                            combined = ' & '.join(poi_list[:2])
                            return f"{city_part}: {combined}"
                        return basic_text
                    else:
                        return f"{city_part}: {poi_list[0]}"
                return basic_text
            
            # Basic is "City, State" format - extract city
            city = basic_text.split(',')[0].strip()
            
            if poi_text:
                poi_list = [p.strip() for p in poi_text.split(',')]
                
                # Combine multiple POIs
                if len(poi_list) >= 2:
                    combined = ' & '.join(poi_list[:2])
                    if len(f"{city}: {combined}") <= 60:
                        return f"{city}: {combined}"
                    return f"{city}: {poi_list[0]}"
                
                # Single POI
                return f"{city}: {poi_list[0]}"
            
            return basic_text
        
        # Create watermarks in both languages
        original = create_single_watermark(basic, poi)
        english = create_single_watermark(basic_en, poi_en)
        
        # Format bilingual display
        if original != english:
            # Different languages - show both
            bilingual = f"{original} ({english})"
        else:
            # Same language - just one version
            bilingual = original
        
        return {
            'original': original,
            'english': english,
            'bilingual': bilingual
        }


class LocationEnhancementCache:
    """Manages Ollama-enhanced location data in master.json using proper UPSERT."""
    
    def __init__(self, master_store):
        """
        Args:
            master_store: MasterStore instance for accessing master.json with UPSERT
        """
        self.master_store = master_store
    
    def get(self, image_path: str) -> Optional[Dict]:
        """Get cached Ollama enhancement for image from master.json."""
        entry = self.master_store.get(image_path)
        if entry and 'location' in entry:
            location = entry['location']
            if isinstance(location, dict):
                return location.get('ollama_enhanced')
        return None
    
    def set(self, image_path: str, enhancement: Dict):
        """Cache Ollama enhancement in master.json using UPSERT (no data loss)."""
        from utils.time_utils import utc_now_iso_z
        
        # Add timestamp to track when enhanced
        enhancement['enhanced_at'] = utc_now_iso_z()
        
        # UPSERT into master.json: location.ollama_enhanced
        # This merges with existing location data, doesn't overwrite
        entry = self.master_store.ensure_entry(image_path)
        
        if 'location' not in entry:
            entry['location'] = {}
        
        if not isinstance(entry['location'], dict):
            # Handle case where location is just a string
            entry['location'] = {'display_name': entry['location']}
        
        entry['location']['ollama_enhanced'] = enhancement
        
        # Mark stage and auto-save via MasterStore
        self.master_store.mark_stage(image_path, 'ollama_enhancement')
        if self.master_store.auto_save:
            self.master_store.save()
    
    def get_stats(self) -> Dict:
        """Get cache statistics from master.json."""
        count = 0
        for entry in self.master_store.data.values():
            if isinstance(entry.get('location'), dict):
                if 'ollama_enhanced' in entry['location']:
                    count += 1
        
        return {
            'total_entries': count,
            'storage': 'master.json (consolidated)'
        }
