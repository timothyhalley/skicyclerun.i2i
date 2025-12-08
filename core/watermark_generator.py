"""
Watermark Generator
Creates formatted watermark text with year, astrological symbol, and location
"""
from datetime import datetime
from typing import Dict, Optional

class WatermarkGenerator:
    # Default brand symbol - mountain peak (universally supported Unicode)
    DEFAULT_SYMBOL = '▲'
    
    def __init__(self, config: Dict):
        self.config = config
        self.watermark_config = config.get('watermark', {})
        self.format_template = self.watermark_config.get('format', 'SkiCycleRun © {year} {symbol} {location}')
        self.symbol = self.watermark_config.get('symbol', self.DEFAULT_SYMBOL)  # Configurable symbol
        self.fixed_year = self.watermark_config.get('fixed_year')  # If set, overrides date calculation
        self.year_offset = self.watermark_config.get('year_offset', 1)
        # Landmark inclusion
        self.include_landmark = bool(self.watermark_config.get('include_landmark', False))
        self.landmark_min_score = float(self.watermark_config.get('landmark_min_score', 0.6))
        self.landmark_max_distance_m = int(self.watermark_config.get('landmark_max_distance_m', 300))
        self.landmark_format = self.watermark_config.get('landmark_format', ' — {name}')
    
    def generate_watermark(self, location: str, date: Optional[datetime] = None, landmark: Optional[str] = None) -> str:
        """Generate watermark text"""
        # Use fixed year if configured, otherwise calculate from date
        if self.fixed_year:
            year = self.fixed_year
        else:
            if date is None:
                date = datetime.now()
            year = date.year + self.year_offset
        
        # If no location, just use copyright and symbol
        if not location or location == 'Unknown Location' or location.strip() == '':
            watermark = f"SkiCycleRun © {year} {self.symbol}"
        else:
            # Format using template - support both old 'astro_symbol' and new 'symbol' placeholders
            watermark = self.format_template.format(
                year=year,
                symbol=self.symbol,
                astro_symbol=self.symbol,  # Backward compatibility
                location=location
            )
        # Optionally append landmark
        if landmark:
            watermark += self.landmark_format.format(name=landmark)
        
        return watermark
    
    def generate_from_metadata(self, metadata: Dict) -> str:
        """Generate watermark from extracted metadata"""
        # PRIORITY 1: Check for LLM-generated watermark
        llm_analysis = metadata.get('llm_image_analysis', {})
        if llm_analysis and llm_analysis.get('watermark'):
            llm_watermark = llm_analysis.get('watermark', '').strip()
            if llm_watermark and llm_watermark.lower() not in ['unknown', 'none', '']:
                # Use LLM watermark directly - it already includes location and context
                return llm_watermark
        
        # FALLBACK: Use old location-based method
        location = metadata.get('location_formatted', '')
        landmark_name: Optional[str] = None
        if self.include_landmark:
            landmarks = metadata.get('landmarks') or []
            # Pick the first landmark meeting thresholds
            for lm in landmarks:
                score = float(lm.get('score') or 1.0)
                dist = lm.get('distance_m')
                if dist is not None and self.landmark_max_distance_m and dist > self.landmark_max_distance_m:
                    continue
                if score < self.landmark_min_score:
                    continue
                name = lm.get('name')
                if name:
                    landmark_name = name
                    break
        
        # Try to get date from EXIF if available
        date = None
        # Prefer UTC if available
        date_taken = metadata.get('date_taken_utc') or metadata.get('date_taken')
        if date_taken:
            try:
                if isinstance(date_taken, str):
                    # Handle ISO format with timezone
                    date = datetime.fromisoformat(date_taken.replace('Z', '+00:00'))
                else:
                    date = date_taken
            except:
                date = datetime.now()
        else:
            date = datetime.now()
        
        return self.generate_watermark(location, date, landmark=landmark_name)
