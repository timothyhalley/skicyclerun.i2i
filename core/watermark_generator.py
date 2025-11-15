"""
Watermark Generator
Creates formatted watermark text with year, astrological symbol, and location
"""
from datetime import datetime
from typing import Dict, Optional

class WatermarkGenerator:
    # Brand symbol - mountain peak (universally supported Unicode)
    BRAND_SYMBOL = '▲'  # Simple, clean, always renders correctly
    
    def __init__(self, config: Dict):
        self.config = config
        self.watermark_config = config.get('watermark', {})
        self.format_template = self.watermark_config.get('format', 'SkiCycleRun © {year} {astro_symbol} {location}')
        self.year_offset = self.watermark_config.get('year_offset', 1)
        # Landmark inclusion
        self.include_landmark = bool(self.watermark_config.get('include_landmark', False))
        self.landmark_min_score = float(self.watermark_config.get('landmark_min_score', 0.6))
        self.landmark_max_distance_m = int(self.watermark_config.get('landmark_max_distance_m', 300))
        self.landmark_format = self.watermark_config.get('landmark_format', ' — {name}')
    
    def get_brand_symbol(self) -> str:
        """Get brand symbol (ski/cycle/run icons)"""
        return self.BRAND_SYMBOL
    
    def generate_watermark(self, location: str, date: Optional[datetime] = None, landmark: Optional[str] = None) -> str:
        """Generate watermark text"""
        if date is None:
            date = datetime.now()
        
        year = date.year + self.year_offset
        brand_symbol = self.get_brand_symbol()
        
        # If no location, just use copyright and symbol
        if not location or location == 'Unknown Location' or location.strip() == '':
            watermark = f"SkiCycleRun © {year} {brand_symbol}"
        else:
            # Use brand symbol in place of astro_symbol
            watermark = self.format_template.format(
                year=year,
                astro_symbol=brand_symbol,  # Keep template variable name for compatibility
                location=location
            )
        # Optionally append landmark
        if landmark:
            watermark += self.landmark_format.format(name=landmark)
        
        return watermark
    
    def generate_from_metadata(self, metadata: Dict) -> str:
        """Generate watermark from extracted metadata"""
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
