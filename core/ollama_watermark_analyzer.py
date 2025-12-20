"""  
Ollama Watermark Analyzer
Enhanced 6-stage image analysis using Ollama LLMs with GPS grounding and POI context
Generates rich, contextual watermarks from GPS coordinates, nearby POIs, and vision analysis
"""
import base64
import json
import time
import requests
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from utils.logger import logInfo, logWarn, logError


class OllamaWatermarkAnalyzer:
    """Enhanced image analyzer using Ollama with 6-stage GPS-grounded pipeline"""
    
    def __init__(self, config: Dict, geocode_cache_path: Optional[str] = None):
        """
        Initialize analyzer with configuration
        
        Args:
            config: Pipeline configuration dict with llm_image_analysis section
            geocode_cache_path: Path to geocode_cache.json for POI lookup
        """
        self.config = config
        self.llm_config = config.get('llm_image_analysis', {})
        
        self.endpoint = self.llm_config.get('endpoint', 'http://localhost:11434')
        
        # Model configuration
        self.models = {
            'poi_research': self.llm_config.get('poi_research_model', 'ministral-3:8b'),
            'vision': self.llm_config.get('vision_model', 'devstral-small-2:24b'),
            'content_generation': self.llm_config.get('content_model', 'devstral-small-2:24b')
        }
        
        # Stage-specific configs
        self.poi_research_config = {
            'temperature': self.llm_config.get('poi_research_temperature', 0.3),
            'num_predict': self.llm_config.get('poi_research_tokens', 250)
        }
        self.vision_config = {
            'temperature': self.llm_config.get('vision_temperature', 0.3),
            'num_predict': self.llm_config.get('vision_tokens', 500),
            'timeout': self.llm_config.get('vision_timeout', 300)
        }
        self.content_config = {
            'temperature': self.llm_config.get('content_temperature', 0.5),
            'top_p': self.llm_config.get('content_top_p', 0.9),
            'num_predict': self.llm_config.get('content_tokens', 400),
            'timeout': self.llm_config.get('content_timeout', 300)
        }
        
        self.prompt_template_path = self.llm_config.get('prompt_template', 'config/ollama_prompt_template.txt')
        self.activity_prompt_template_path = self.llm_config.get('activity_prompt_template', 'config/ollama_image_analysis_template.txt')
        self.debug_prompt = self.llm_config.get('debug_prompt', False)
        
        # Load geocode cache for POI lookups
        self.geocode_cache = {}
        if geocode_cache_path:
            try:
                cache_path = Path(geocode_cache_path)
                if cache_path.exists():
                    with open(cache_path, 'r', encoding='utf-8') as f:
                        self.geocode_cache = json.load(f)
                    logInfo(f"Loaded geocode cache with {len(self.geocode_cache)} locations")
            except Exception as e:
                logWarn(f"Failed to load geocode cache: {e}")
        
        # Verify Ollama is available
        if not self._check_ollama_available():
            raise ConnectionError(f"Ollama not available at {self.endpoint}")
    
    def _check_ollama_available(self) -> bool:
        """Check if Ollama is running and accessible"""
        try:
            response = requests.get(f"{self.endpoint}/api/tags", timeout=3)
            return response.status_code == 200
        except:
            return False
    
    def _get_pois_from_cache(self, lat: float, lon: float) -> List[Dict]:
        """Lookup POI data from geocode cache using GPS coordinates
        
        Args:
            lat: Latitude
            lon: Longitude
            
        Returns:
            List of POI dicts (empty if not found)
        """
        cache_key = f"{lat:.6f},{lon:.6f}"
        cached_data = self.geocode_cache.get(cache_key, {})
        return cached_data.get('nearby_pois', [])
    
    def _log_prompt(self, image_name: str, stage: str, prompt: str):
        """Log populated prompt to logs folder if debug_prompt is enabled
        
        Args:
            image_name: Name of the image file
            stage: Stage identifier (e.g., 'stage5_activity_analysis', 'stage6_content_generation')
            prompt: The populated prompt text
        """
        if not self.debug_prompt:
            return
        
        try:
            logs_dir = Path('logs')
            logs_dir.mkdir(exist_ok=True)
            
            # Create filename: image_name_stage.txt
            log_filename = f"{Path(image_name).stem}_{stage}.txt"
            log_path = logs_dir / log_filename
            
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write(f"# Stage: {stage}\n")
                f.write(f"# Image: {image_name}\n")
                f.write(f"# Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("\n" + "="*80 + "\n\n")
                f.write(prompt)
            
            logInfo(f"📝 Logged {stage} prompt to {log_path}")
        except Exception as e:
            logWarn(f"Failed to log prompt: {e}")
    
    def research_poi(self, poi_name: str, poi_classification: str, city: str, 
                    country: str, lat: float, lon: float) -> dict:
        """
        Stage 3: Research POI using GPS grounding
        
        Args:
            poi_name: Name of the POI
            poi_classification: OSM classification (ignored in prompt)
            city: City name
            country: Country name
            lat: GPS latitude
            lon: GPS longitude
            
        Returns:
            dict with brief_context or error
        """
        # Prompt without OSM classification to avoid bias
        prompt = f"""What is {poi_name} at GPS coordinates {lat:.4f}, {lon:.4f} in {city}, {country}?

What TYPE of place is this? (museum, gallery, shop, restaurant, attraction, monument, etc.)
What is it known for? What can visitors experience there?

Provide 2-3 sentences of FACTS only. Use the GPS location to identify it accurately."""
        
        model = self.models.get('poi_research', 'ministral-3:8b')
        temp = self.poi_research_config.get('temperature', 0.3)
        tokens = self.poi_research_config.get('num_predict', 250)
        
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temp,
                "num_predict": tokens
            }
        }
        
        try:
            response = requests.post(
                f"{self.endpoint}/api/generate", 
                json=payload, 
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                brief_context = result.get('response', '').strip()
                response.close()
                return {"brief_context": brief_context}
            else:
                response.close()
                return {"error": f"HTTP {response.status_code}"}
                
        except Exception as e:
            return {"error": str(e)}
    
    def analyze_activity(self, base64_image: str, pois: List[dict], image_name: str = "unknown") -> dict:
        """
        Stage 5: Analyze image activity and scene type using vision model
        
        Args:
            base64_image: Base64-encoded image
            pois: List of nearby POIs with distance
            image_name: Name of image file for logging
            
        Returns:
            dict with activity, scene_type, is_interior, closest_poi
        """
        # Determine closest POI
        closest_poi = None
        if pois and len(pois) > 0:
            closest_poi = pois[0]  # Already sorted by distance
        
        # Load activity prompt template
        try:
            template_path = Path(self.activity_prompt_template_path)
            if template_path.exists():
                with open(template_path, 'r', encoding='utf-8') as f:
                    prompt = f.read()
            else:
                # Fallback to hardcoded prompt
                prompt = """Describe what you see in this photo. What activity or scene is depicted?

Is this INTERIOR (inside a building) or EXTERIOR (outdoors)?

RULES:
- Be specific and descriptive about the activity/scene
- Identify key subjects, actions, or elements
- Classify the scene type accurately
- Determine if interior or exterior based on visual cues

Answer in JSON only:
{
  "activity": "brief description of scene",
  "scene_type": "urban/nature/historic/transit/beach/waterfront/mountain/other",
  "is_interior": true/false
}"""
                logWarn(f"Activity prompt template not found at {template_path}, using fallback")
        except Exception as e:
            # Fallback prompt
            prompt = """Describe what you see in this photo. What activity or scene is depicted?

Answer in JSON only:
{
  "activity": "brief description of scene",
  "scene_type": "urban/nature/historic/transit/beach/waterfront/mountain/other",
  "is_interior": true/false
}"""
            logWarn(f"Error loading activity prompt template: {e}")
        
        # Log prompt if debug enabled
        self._log_prompt(image_name, "stage5_activity_analysis", prompt)
        
        model = self.models.get('vision', 'llava:7b')
        temp = self.vision_config.get('temperature', 0.3)
        tokens = self.vision_config.get('num_predict', 250)
        
        payload = {
            "model": model,
            "prompt": prompt,
            "images": [base64_image],
            "stream": False,
            "options": {
                "temperature": temp,
                "num_predict": tokens
            }
        }
        
        # Get timeout from config (default 120s for vision)
        vision_timeout = self.vision_config.get('timeout', 120)
        
        try:
            response = requests.post(
                f"{self.endpoint}/api/generate",
                json=payload,
                timeout=vision_timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                raw_response = result.get('response', '').strip()
                response.close()
                
                # Parse JSON response
                try:
                    # Extract JSON from response
                    if '```json' in raw_response:
                        json_str = raw_response.split('```json')[1].split('```')[0].strip()
                    elif '```' in raw_response:
                        json_str = raw_response.split('```')[1].split('```')[0].strip()
                    else:
                        json_str = raw_response
                    
                    parsed = json.loads(json_str)
                    
                    # Return all individual fields for Stage 6 to use
                    return {
                        "primary_subject": parsed.get('primary_subject', ''),
                        "secondary_elements": parsed.get('secondary_elements', ''),
                        "atmosphere": parsed.get('atmosphere', ''),
                        "actions": parsed.get('actions', ''),
                        "visible_text": parsed.get('visible_text', ''),
                        "landmark_clues": parsed.get('landmark_clues', ''),
                        "composition": parsed.get('composition', ''),
                        "scene_type": parsed.get('scene_type', 'unknown'),
                        "is_interior": parsed.get('is_interior', False),
                        "closest_poi": closest_poi
                    }
                    
                except json.JSONDecodeError as e:
                    # Fallback parsing - clean up incomplete JSON/code fences
                    logWarn(f"Failed to parse Stage 5 JSON response: {e}")
                    
                    # Extract activity text from incomplete JSON
                    activity_text = raw_response
                    
                    # Remove JSON code fences and incomplete braces
                    activity_text = activity_text.replace('```json', '').replace('```', '')
                    activity_text = activity_text.replace('{', '').replace('}', '')
                    activity_text = activity_text.replace('"primary_subject":', '').replace('"scene_type":', '')
                    activity_text = activity_text.replace('"is_interior":', '')
                    activity_text = activity_text.strip().strip(',').strip('"').strip()
                    
                    # Try to extract just the activity description
                    if activity_text:
                        # Take first meaningful sentence
                        lines = [line.strip() for line in activity_text.split('\n') if line.strip()]
                        activity_text = lines[0] if lines else activity_text
                    
                    return {
                        "primary_subject": activity_text if activity_text else "Scene description unavailable",
                        "secondary_elements": "",
                        "atmosphere": "",
                        "actions": "",
                        "visible_text": "",
                        "landmark_clues": "",
                        "composition": "",
                        "scene_type": "unknown",
                        "is_interior": False,
                        "closest_poi": closest_poi
                    }
            else:
                response.close()
                return {"error": f"HTTP {response.status_code}"}
                
        except Exception as e:
            return {"error": str(e)}
    
    def build_programmatic_watermark(self, metadata: dict, primary_subject: dict) -> str:
        """
        Build programmatic watermark following format:
        {city} {state} {emoji} SkiCyclerun © {year}
        
        Example: Tucson Arizona 🎿 SkiCyclerun © 2026
        
        Args:
            metadata: Full metadata with location, pois, gps
            primary_subject: Results from analyze_activity (not used, kept for compatibility)
            
        Returns:
            Formatted watermark string
        """
        location = metadata.get('location', {})
        country = location.get('country', 'Unknown')
        city = location.get('city', 'Unknown')
        state = location.get('state', '')
        
        # Build location part: city + state (for US/Canada) or city + country (others)
        if country in ['Canada', 'United States'] and state:
            location_part = f"{city} {state}"
        else:
            # Other countries: just city and country
            location_part = f"{city} {country}"
        
        # Get emoji and copyright from config (with defaults)
        watermark_config = self.config.get('watermark', {})
        symbol = watermark_config.get('symbol', '🎿')
        fixed_year = watermark_config.get('fixed_year')
        year = fixed_year if fixed_year else datetime.now().year + watermark_config.get('year_offset', 1)
        
        # Build watermark: {city} {state} {emoji} {copyright}
        # Example: Tucson Arizona 🎿 SkiCyclerun © 2026
        return f"{location_part} {symbol} SkiCyclerun © {year}"
    
    def generate_watermark_content(self, metadata: dict, primary_subject: dict, 
                                   base64_image: str, image_name: str = "unknown") -> dict:
        """
        Stage 6: Generate final watermark and description using text-only model
        
        Args:
            metadata: Full metadata with location, pois, gps
            primary_subject: Results from analyze_activity
            base64_image: Base64 image (not used in Stage 6, kept for compatibility)
            image_name: Name of image file for logging
            
        Returns:
            dict with watermark, description, watermark_line1, watermark_line2
        """
        # Load prompt template
        template_path = Path(self.prompt_template_path)
        if not template_path.exists():
            logError(f"Prompt template not found: {template_path}")
            return {"error": "Prompt template not found"}
        
        with open(template_path, 'r', encoding='utf-8') as f:
            prompt_template = f.read().strip()
        
        # Determine watermark_line2 format
        location = metadata.get('location', {})
        country = location.get('country', '')
        city = location.get('city', 'Unknown')
        state = location.get('state', '')
        
        if country in ['United States', 'Canada']:
            watermark_line2_format = f"{city}, {state}, {country}"
        else:
            watermark_line2_format = f"{city}, {country}"
        
        # Build comprehensive activity description from structured analysis
        primary = primary_subject.get('primary_subject', '')
        actions = primary_subject.get('actions', '')
        atmosphere = primary_subject.get('atmosphere', '')
        secondary = primary_subject.get('secondary_elements', '')
        visible_text = primary_subject.get('visible_text', '')
        landmark_clues = primary_subject.get('landmark_clues', '')
        composition = primary_subject.get('composition', '')
        
        # Ensure text fields are strings (handle cases where they might be lists or dicts)
        if isinstance(visible_text, list):
            visible_text = ', '.join(str(x) for x in visible_text)
        elif isinstance(visible_text, dict):
            visible_text = str(visible_text)
        
        if isinstance(landmark_clues, list):
            landmark_clues = ', '.join(str(x) for x in landmark_clues)
        elif isinstance(landmark_clues, dict):
            landmark_clues = str(landmark_clues)
        
        # Ensure all other fields are also strings (handle lists and dicts)
        if isinstance(primary, list):
            primary = ', '.join(str(x) for x in primary)
        elif not isinstance(primary, str):
            primary = str(primary)
            
        if isinstance(actions, list):
            actions = ', '.join(str(x) for x in actions)
        elif not isinstance(actions, str):
            actions = str(actions)
            
        if isinstance(atmosphere, list):
            atmosphere = ', '.join(str(x) for x in atmosphere)
        elif not isinstance(atmosphere, str):
            atmosphere = str(atmosphere)
            
        if isinstance(secondary, list):
            secondary = ', '.join(str(x) for x in secondary)
        elif not isinstance(secondary, str):
            secondary = str(secondary)
            
        if isinstance(composition, dict):
            # Extract composition dict fields and format nicely
            comp_parts = []
            if composition.get('framing'):
                comp_parts.append(composition['framing'])
            if composition.get('lighting'):
                comp_parts.append(composition['lighting'])
            if composition.get('perspective'):
                comp_parts.append(composition['perspective'])
            composition = ', '.join(comp_parts) if comp_parts else str(composition)
        elif isinstance(composition, list):
            composition = ', '.join(str(x) for x in composition)
        elif not isinstance(composition, str):
            composition = str(composition)
        
        # Build rich activity description
        activity_parts = []
        if primary:
            activity_parts.append(f"PRIMARY SUBJECT: {primary}")
        if actions:
            activity_parts.append(f"ACTIONS: {actions}")
        if atmosphere:
            activity_parts.append(f"ATMOSPHERE: {atmosphere}")
        if secondary:
            activity_parts.append(f"BACKGROUND/CONTEXT: {secondary}")
        if visible_text and visible_text.lower() not in ['none', 'n/a', 'no text visible', 'no visible text']:
            activity_parts.append(f"VISIBLE TEXT: {visible_text}")
        if landmark_clues and landmark_clues.lower() not in ['none', 'n/a', 'no landmarks visible', 'no landmarks']:
            activity_parts.append(f"VISUAL LANDMARKS: {landmark_clues}")
        if composition:
            activity_parts.append(f"COMPOSITION: {composition}")
        
        activity = "\n".join(activity_parts) if activity_parts else "Scene analysis unavailable"
        
        scene_type = primary_subject.get('scene_type', 'unknown')
        is_interior = primary_subject.get('is_interior', False)
        closest_poi = primary_subject.get('closest_poi')
        
        # Format POI list WITH distance filtering based on interior/exterior
        # Interior scenes: only include POIs < 25m (at same location)
        # Exterior scenes: only include POIs < 100m (reasonably nearby)
        poi_text = ""
        distance_threshold = 25 if is_interior else 100
        
        if metadata.get('nearby_pois'):
            poi_lines = []
            for poi in metadata['nearby_pois']:
                poi_distance = poi.get('distance_m', 0)
                
                # Apply distance filter based on interior/exterior
                if poi_distance < distance_threshold:
                    research = poi.get('research', '')
                    if research and research != 'No specific information available.':
                        poi_lines.append(f"• {poi['name']} ({int(poi_distance)}m): {research}")
                    else:
                        poi_lines.append(f"• {poi['name']} ({int(poi_distance)}m)")
            
            if poi_lines:
                poi_text = '\n'.join(poi_lines)
            else:
                if is_interior:
                    poi_text = "None within 25m (interior photo - residence or private location)"
                else:
                    poi_text = "None within 100m"
        else:
            poi_text = "None found"
        
        # Interior/Exterior text
        interior_exterior_text = "Interior photo" if is_interior else "Exterior photo"
        
        # Ground Zero (street context)
        ground_zero = ""
        street_address = location.get('street_address')
        street_research = location.get('street_research')
        if street_address and scene_type == 'urban':
            if street_research:
                ground_zero = f"📍 GROUND ZERO: {street_address}\nAbout this street: {street_research}"
            else:
                ground_zero = f"📍 GROUND ZERO: {street_address}"
        
        # POI context from closest POI (using same distance threshold)
        poi_context = ""
        if closest_poi:
            poi_distance = closest_poi.get('distance_m', 0)
            
            # Use same threshold as POI list filtering
            if poi_distance < distance_threshold:
                poi_research = closest_poi.get('research', '')
                if poi_research:
                    poi_context = f"This is near {closest_poi['name']}, located {int(poi_distance)}m away.\n\nContext: {poi_research}"
            else:
                # POI too far away for this scene type
                if is_interior:
                    poi_context = f"Closest POI is {closest_poi['name']} at {int(poi_distance)}m - too far for interior scene. This appears to be a residence or private location."
                else:
                    poi_context = f"Closest POI is {closest_poi['name']} at {int(poi_distance)}m - no landmarks in immediate vicinity."
        
        # Format nearby places list with distances and relevance thresholds
        nearby_places = ""
        if metadata.get('nearby_pois'):
            # Set distance threshold based on interior/exterior
            distance_threshold = 50 if is_interior else 500
            
            place_entries = []
            for poi in metadata['nearby_pois'][:5]:  # Top 5 places
                poi_name = poi['name']
                poi_distance = poi.get('distance_m', 0)
                
                # Round distance and format based on threshold
                rounded_distance = int(round(poi_distance))
                if rounded_distance > distance_threshold:
                    distance_str = f">{distance_threshold}m"
                else:
                    distance_str = f"{rounded_distance}m"
                
                place_entries.append(f"{poi_name} ({distance_str})")
            
            nearby_places = ", ".join(place_entries) if place_entries else "None found"
        else:
            nearby_places = "None found"
        
        # Select random writing style
        import random
        writing_styles = self.llm_config.get('writing_styles', [])
        selected_author = None  # Store author name for metadata
        if writing_styles:
            selected_style = random.choice(writing_styles)
            selected_author = selected_style['author']
            # IMPORTANT: Do NOT mention author name - just use style description
            # This prevents LLM from referencing the author in the text
            writing_style = selected_style['style']
        else:
            writing_style = "Write clearly and engagingly."
        
        # Get display_name (full address)
        display_name = location.get('display_name', f"{city}, {country}")
        
        # Replace template placeholders
        prompt_text = prompt_template.format(
            writing_style=writing_style,
            display_name=display_name,
            photo_city=city,
            photo_state=state if state else "N/A",
            photo_country=country,
            nearby_places=nearby_places,
            ground_zero=ground_zero if ground_zero else "",
            photo_activity=activity,
            photo_scene_type=scene_type,
            interior_exterior_text=interior_exterior_text,
            nearby_pois=poi_text,
            poi_context=poi_context if poi_context else "No specific landmark context available."
        )
        
        # Log prompt if debug enabled
        self._log_prompt(image_name, "stage6_content_generation", prompt_text)
        
        # Send to LLM (text-only, no image)
        model = self.models.get('content_generation', 'mixtral:8x7b')
        temp = self.content_config.get('temperature', 0.5)
        top_p = self.content_config.get('top_p', 0.9)
        tokens = self.content_config.get('num_predict', 400)
        timeout = self.content_config.get('timeout', 300)
        
        payload = {
            "model": model,
            "prompt": prompt_text,
            "stream": False,
            "options": {
                "temperature": temp,
                "top_p": top_p,
                "num_predict": tokens
            }
        }
        
        try:
            response = requests.post(
                f"{self.endpoint}/api/generate",
                json=payload,
                timeout=timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                content = result.get('response', '').strip()
                response.close()
                
                # DEBUG: Show what LLM returned
                print("\n" + "🔍 DEBUG: LLM RESPONSE" + "=" * 60)
                print(content[:500] if len(content) > 500 else content)
                print("=" * 80 + "\n")
                
                # Parse response - prompt now asks for TWO sections only:
                # TRAVEL BLOG: [paragraph]
                # SUMMARY: [one sentence]
                # (WATERMARK is now programmatic, not from LLM)
                travel_blog = ""
                summary = ""
                watermark_text = ""  # Keep for backward compatibility but not used
                
                # Use case-insensitive regex for section markers
                import re
                
                # Extract TRAVEL BLOG section (case-insensitive)
                travel_match = re.search(r'TRAVEL\s+BLOG\s*:\s*', content, re.IGNORECASE)
                if travel_match:
                    start_pos = travel_match.end()
                    # Get text after TRAVEL BLOG: up to SUMMARY:
                    summary_match = re.search(r'SUMMARY\s*:\s*', content[start_pos:], re.IGNORECASE)
                    if summary_match:
                        travel_blog = content[start_pos:start_pos + summary_match.start()].strip()
                    else:
                        travel_blog = content[start_pos:].strip()
                
                # Extract SUMMARY section (case-insensitive)
                summary_match = re.search(r'SUMMARY\s*:\s*', content, re.IGNORECASE)
                if summary_match:
                    start_pos = summary_match.end()
                    summary = content[start_pos:].strip()
                
                # Fallback if sections not found
                if not travel_blog and not summary:
                    logWarn(f"⚠️  Failed to parse LLM response sections - attempting fallback parsing")
                    
                    # Fallback: use entire content as travel_blog
                    travel_blog = content.strip()
                    
                    # Try to extract first sentence as summary
                    first_sentence = content.split('.')[0].strip() if '.' in content else content[:150]
                    summary = first_sentence
                    
                    # Log what we got
                    if not travel_blog:
                        logWarn(f"⚠️  LLM returned unparseable content (length: {len(content)})")
                        logWarn(f"    First 200 chars: {content[:200]}")
                
                # CRITICAL CLEANUP: Remove common LLM artifacts
                import re
                
                def clean_text(text):
                    """Remove emoji prefixes, section header labels, markdown formatting, quotes, and extra spaces"""
                    # Remove emoji prefixes (🔖, ✨, 📍, etc.)
                    text = re.sub(r'^[\U0001F300-\U0001F9FF\U00002600-\U000027BF\U0001F600-\U0001F64F\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]+\s*', '', text)
                    
                    # Remove markdown bold formatting (**text** -> text)
                    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
                    
                    # Remove ALL section header prefixes (case insensitive)
                    # "travel blog:", "TRAVEL BLOG:", "summary:", "SUMMARY:", "watermark:", "WATERMARK:"
                    text = re.sub(r'^travel\s+blog\s*:\s*', '', text, flags=re.IGNORECASE)
                    text = re.sub(r'^summary\s*:\s*', '', text, flags=re.IGNORECASE)
                    text = re.sub(r'^watermark\s*:\s*', '', text, flags=re.IGNORECASE)
                    
                    # Remove escaped quotes
                    text = text.replace('\\"', '"').replace("\\'", "'")
                    
                    # Remove literal \n characters
                    text = text.replace('\\n', ' ')
                    
                    # Remove leading/trailing quotes
                    text = text.strip('"').strip("'").strip()
                    
                    # Collapse multiple spaces
                    text = re.sub(r'\s+', ' ', text).strip()
                    
                    return text
                
                # Clean all three fields (note: watermark_text from LLM is deprecated)
                travel_blog = clean_text(travel_blog)
                summary = clean_text(summary)
                watermark_text = clean_text(watermark_text)  # Keep for backward compatibility
                
                # Build programmatic watermark
                programmatic_watermark = self.build_programmatic_watermark(metadata, primary_subject)
                
                # Return clean, non-duplicated fields
                # - travel_blog: Full descriptive paragraph about scene
                # - summary: Summation focusing on subject/location/essence
                # - programmatic_watermark: Formatted watermark (landmark + location + copyright)
                # - watermark_text: LLM-generated (DEPRECATED - keep for backward compatibility)
                # - writing_style: Author name used for content generation
                return {
                    "raw_response": content,
                    "travel_blog": travel_blog,
                    "summary": summary,
                    "programmatic_watermark": programmatic_watermark,
                    "watermark_text": watermark_text,  # Deprecated
                    "writing_style": selected_author  # Store author name for metadata
                }
            else:
                response.close()
                return {"error": f"HTTP {response.status_code}"}
                
        except Exception as e:
            return {"error": str(e)}
    
    def analyze(self, image_path: str, metadata: dict) -> dict:
        """
        Run full 6-stage analysis pipeline with EXACT logging from debug/test_ollama_structured.py
        
        Args:
            image_path: Path to image file
            metadata: Existing metadata with gps, location, nearby_pois
            
        Returns:
            dict with watermark, description, primary_subject, timing, etc.
        """
        start_time = time.time()
        result = {}
        
        # Load and encode image
        try:
            with open(image_path, 'rb') as f:
                image_data = f.read()
            base64_image = base64.b64encode(image_data).decode('utf-8')
        except Exception as e:
            logError(f"Failed to load image: {e}")
            return {"error": f"Image load failed: {e}"}
        
        # Extract required data from metadata
        location = metadata.get('location', {})
        gps = metadata.get('gps', {})
        
        # GPS data uses 'lat'/'lon' keys (not 'latitude'/'longitude')
        if not gps or not gps.get('lat'):
            logWarn("No GPS data in metadata - cannot run enhanced analysis")
            return {"error": "No GPS data available"}
        
        # Lookup POI data from geocode cache (not from metadata)
        cache_key = f"{gps['lat']:.6f},{gps['lon']:.6f}"
        print(f"   🔍 Looking up POI data for cache key: {cache_key}")
        nearby_pois = self._get_pois_from_cache(gps['lat'], gps['lon'])
        print(f"   📍 Found {len(nearby_pois) if nearby_pois is not None else 'None'} POIs (type: {type(nearby_pois)})")
        if not nearby_pois:
            logWarn(f"No POI data found in geocode cache for {cache_key}")
        
        # STAGE 3: Research POIs and Location (EXACT from debug script)
        print("📚 STAGE 3: Research POIs and Location")
        print("-" * 80)
        stage3_start = time.time()
        
        if nearby_pois:
            for poi in nearby_pois:
                print(f"   Researching: {poi['name']} ({poi.get('category', 'landmark')})")
                
                poi_research = self.research_poi(
                    poi_name=poi.get('name', 'Unknown'),
                    poi_classification=poi.get('category', 'landmark'),
                    city=location.get('city', 'Unknown'),
                    country=location.get('country', 'Unknown'),
                    lat=gps['lat'],
                    lon=gps['lon']
                )
                
                if 'error' not in poi_research:
                    poi['research'] = poi_research.get('brief_context', '')
                else:
                    poi['research'] = 'No specific information available.'
        
        stage3_time = time.time() - stage3_start
        print(f"   ✓ Researched {len(nearby_pois) if nearby_pois else 0} POIs")
        print(f"   ⏱️  Time: {stage3_time:.2f}s")
        print()
        
        # STAGE 5: Analyze activity and scene (EXACT from debug script)
        print("👁️  STAGE 5: Analyze activity & photographer location")
        print(f"   Model: {self.models.get('vision', 'unknown')} | Timeout: {self.vision_config.get('timeout', 300)}s")
        print("-" * 80)
        stage5_start = time.time()
        primary_subject = self.analyze_activity(base64_image, nearby_pois, Path(image_path).name)
        stage5_time = time.time() - stage5_start
        
        if 'error' in primary_subject:
            logError(f"Activity analysis failed: {primary_subject['error']}")
            return {"error": primary_subject['error']}
        
        print(f"   PRIMARY: {primary_subject.get('primary_subject', 'N/A')}")
        print(f"   ACTIONS: {primary_subject.get('actions', 'N/A')}")
        print(f"   ATMOSPHERE: {primary_subject.get('atmosphere', 'N/A')}")
        print(f"   SECONDARY: {primary_subject.get('secondary_elements', 'N/A')[:80]}...")
        if primary_subject.get('visible_text'):
            print(f"   TEXT: {primary_subject.get('visible_text')}")
        if primary_subject.get('landmark_clues'):
            print(f"   LANDMARKS: {primary_subject.get('landmark_clues')}")
        print(f"   Scene type: {primary_subject.get('scene_type', 'N/A')}")
        print(f"   Interior: {primary_subject.get('is_interior', False)}")
        
        closest = primary_subject.get('closest_poi')
        if closest:
            print(f"   📍 Photographer at: {closest['name']} ({closest.get('distance_m', 0)}m)")
        else:
            print(f"   📍 Photographer at: Unknown location")
        
        print(f"   ⏱️  Time: {stage5_time:.2f}s")
        print()
        
        # Brief pause before final generation (EXACT from debug script)
        print("💤 Allowing model to reset (2s)...")
        time.sleep(2)
        print()
        
        # STAGE 6: Generate watermark and description (EXACT from debug script)
        print("✍️  STAGE 6: Generate final travel content")
        print(f"   Model: {self.models.get('content_generation', 'mixtral:8x7b')}")
        print("-" * 80)
        stage6_start = time.time()
        
        # Update metadata with researched POIs
        metadata_with_research = metadata.copy()
        metadata_with_research['nearby_pois'] = nearby_pois
        
        final_content = self.generate_watermark_content(
            metadata_with_research,
            primary_subject,
            base64_image,
            Path(image_path).name
        )
        stage6_time = time.time() - stage6_start
        
        if 'error' in final_content:
            logError(f"Content generation failed: {final_content['error']}")
            return {"error": final_content['error']}
        
        # Display final content
        print()
        print("📝 FINAL CONTENT:")
        print("=" * 80)
        if 'travel_blog' in final_content:
            print(f"📖 Travel Blog:\n{final_content['travel_blog']}\n")
        if 'summary' in final_content:
            print(f"📌 Summary:\n{final_content['summary']}\n")
        if 'watermark_text' in final_content:
            print(f"🏷️  Watermark Text: {final_content['watermark_text']}")
        print("=" * 80)
        print(f"   ⏱️  Time: {stage6_time:.2f}s")
        print()
        
        # Compile final result with NEW field names (travel_blog, summary, watermark_text)
        total_time = time.time() - start_time
        
        result = {
            "travel_blog": final_content.get('travel_blog', ''),
            "summary": final_content.get('summary', ''),
            "watermark_text": final_content.get('watermark_text', ''),
            "programmatic_watermark": final_content.get('programmatic_watermark', ''),
            "writing_style": final_content.get('writing_style', ''),
            "primary_subject": primary_subject.get('primary_subject', ''),
            "secondary_elements": primary_subject.get('secondary_elements', ''),
            "atmosphere": primary_subject.get('atmosphere', ''),
            "actions": primary_subject.get('actions', ''),
            "visible_text": primary_subject.get('visible_text', ''),
            "landmark_clues": primary_subject.get('landmark_clues', ''),
            "composition": primary_subject.get('composition', ''),
            "scene_type": primary_subject.get('scene_type', ''),
            "is_interior": primary_subject.get('is_interior', False),
            "closest_poi": primary_subject.get('closest_poi'),
            "model": self.models.get('content_generation', 'mixtral:8x7b'),
            "llm_analysis_time": total_time,
            "timing": {
                "poi_research": stage3_time,
                "activity_analysis": stage5_time,
                "content_generation": stage6_time,
                "total": total_time
            }
        }
        
        # Timing summary (EXACT from debug script)
        print("⏱️  TIMING SUMMARY")
        print("=" * 80)
        print(f"Stage 3 (POI Research):      {stage3_time:.2f}s")
        print(f"Stage 5 (Subject Analysis):  {stage5_time:.2f}s")
        print(f"Stage 6 (Final Content):     {stage6_time:.2f}s")
        print("-" * 80)
        print(f"TOTAL:                       {total_time:.2f}s")
        print("=" * 80)
        print()
        
        return result
