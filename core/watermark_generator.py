"""
Watermark Generator
Creates formatted watermark text with year, astrological symbol, and location
"""
from datetime import datetime
from typing import Dict, Optional

class WatermarkGenerator:
    # Astrological symbols (Emoji for better compatibility)
    ASTRO_SYMBOLS = {
        'aries': '♈️',       # Mar 21 - Apr 19
        'taurus': '♉️',      # Apr 20 - May 20
        'gemini': '♊️',      # May 21 - Jun 20
        'cancer': '♋️',      # Jun 21 - Jul 22
        'leo': '♌️',         # Jul 23 - Aug 22
        'virgo': '♍️',       # Aug 23 - Sep 22
        'libra': '♎️',       # Sep 23 - Oct 22
        'scorpio': '♏️',     # Oct 23 - Nov 21
        'sagittarius': '♐️', # Nov 22 - Dec 21
        'capricorn': '♑️',   # Dec 22 - Jan 19
        'aquarius': '♒️',    # Jan 20 - Feb 18
        'pisces': '♓️'       # Feb 19 - Mar 20
    }
    
    def __init__(self, config: Dict):
        self.config = config
        self.watermark_config = config.get('watermark', {})
        self.format_template = self.watermark_config.get('format', 'SkiCycleRun © {year} {astro_symbol} {location}')
        self.year_offset = self.watermark_config.get('year_offset', 1)
    
    def get_astrological_sign(self, date: Optional[datetime] = None) -> str:
        """Get astrological symbol for a given date"""
        if date is None:
            date = datetime.now()
        
        month = date.month
        day = date.day
        
        # Determine zodiac sign
        if (month == 3 and day >= 21) or (month == 4 and day <= 19):
            return self.ASTRO_SYMBOLS['aries']
        elif (month == 4 and day >= 20) or (month == 5 and day <= 20):
            return self.ASTRO_SYMBOLS['taurus']
        elif (month == 5 and day >= 21) or (month == 6 and day <= 20):
            return self.ASTRO_SYMBOLS['gemini']
        elif (month == 6 and day >= 21) or (month == 7 and day <= 22):
            return self.ASTRO_SYMBOLS['cancer']
        elif (month == 7 and day >= 23) or (month == 8 and day <= 22):
            return self.ASTRO_SYMBOLS['leo']
        elif (month == 8 and day >= 23) or (month == 9 and day <= 22):
            return self.ASTRO_SYMBOLS['virgo']
        elif (month == 9 and day >= 23) or (month == 10 and day <= 22):
            return self.ASTRO_SYMBOLS['libra']
        elif (month == 10 and day >= 23) or (month == 11 and day <= 21):
            return self.ASTRO_SYMBOLS['scorpio']
        elif (month == 11 and day >= 22) or (month == 12 and day <= 21):
            return self.ASTRO_SYMBOLS['sagittarius']
        elif (month == 12 and day >= 22) or (month == 1 and day <= 19):
            return self.ASTRO_SYMBOLS['capricorn']
        elif (month == 1 and day >= 20) or (month == 2 and day <= 18):
            return self.ASTRO_SYMBOLS['aquarius']
        else:  # (month == 2 and day >= 19) or (month == 3 and day <= 20)
            return self.ASTRO_SYMBOLS['pisces']
    
    def generate_watermark(self, location: str, date: Optional[datetime] = None) -> str:
        """Generate watermark text"""
        if date is None:
            date = datetime.now()
        
        year = date.year + self.year_offset
        astro_symbol = self.get_astrological_sign(date)
        
        # If no location, just use copyright and symbol
        if not location or location == 'Unknown Location' or location.strip() == '':
            watermark = f"SkiCycleRun © {year} {astro_symbol}"
        else:
            watermark = self.format_template.format(
                year=year,
                astro_symbol=astro_symbol,
                location=location
            )
        
        return watermark
    
    def generate_from_metadata(self, metadata: Dict) -> str:
        """Generate watermark from extracted metadata"""
        location = metadata.get('location_formatted', '')
        
        # Try to get date from EXIF if available
        date = None
        date_taken = metadata.get('date_taken')
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
        
        return self.generate_watermark(location, date)
