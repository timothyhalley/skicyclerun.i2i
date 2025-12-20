"""
Filename Generator
Generates meaningful filenames from metadata and location data
"""
import re
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime


class FilenameGenerator:
    """Generate smart filenames based on metadata and location"""
    
    # Generic patterns that need better names
    GENERIC_PATTERNS = [
        r'^IMG_\d+$',
        r'^DSC_\d+$',
        r'^DCIM_\d+$',
        r'^P\d+$',
        r'^\d{8}_\d{6}$',  # YYYYMMDD_HHMMSS
    ]
    
    @staticmethod
    def is_generic_filename(filename: str) -> bool:
        """Check if filename is generic (IMG_1234, etc)"""
        stem = Path(filename).stem
        for pattern in FilenameGenerator.GENERIC_PATTERNS:
            if re.match(pattern, stem, re.IGNORECASE):
                return True
        return False
    
    @staticmethod
    def slugify(text: str, max_length: int = 50) -> str:
        """Convert text to safe filename slug"""
        # Remove special characters
        text = re.sub(r'[^\w\s-]', '', text)
        # Replace spaces with underscores
        text = re.sub(r'[-\s]+', '_', text)
        # Lowercase and strip
        text = text.lower().strip('_')
        # Limit length
        if len(text) > max_length:
            text = text[:max_length].rstrip('_')
        return text
    
    @staticmethod
    def extract_location_components(location: str) -> Dict[str, Optional[str]]:
        """Parse location string into components"""
        if not location or location == "Unknown Location":
            return {'city': None, 'region': None, 'country': None}
        
        # Split by comma
        parts = [p.strip() for p in location.split(',')]
        
        components = {
            'city': None,
            'region': None,
            'country': None
        }
        
        if len(parts) >= 3:
            # Format: "City, Region, Country"
            components['city'] = parts[0]
            components['region'] = parts[1]
            components['country'] = parts[2]
        elif len(parts) == 2:
            # Format: "City, Country"
            components['city'] = parts[0]
            components['country'] = parts[1]
        elif len(parts) == 1:
            # Just city or country
            components['city'] = parts[0]
        
        return components
    
    @staticmethod
    def extract_meaningful_location(location_dict: Dict) -> Optional[str]:
        """Extract the most meaningful location component from display_name"""
        if not location_dict:
            return None
        
        display_name = location_dict.get('display_name', '')
        city = location_dict.get('city')
        country = location_dict.get('country')
        
        if not display_name:
            return city or country
        
        # Split display_name by comma to get specific location parts
        # Example: "Marina Bay, Marina East, Southeast, Singapore"
        # Example: "Area B (Westside/Swan Lake/Kalamalka Lake), Regional District..."
        parts = [p.strip() for p in display_name.split(',')]
        
        if not parts:
            return city or country
        
        # Get the first part (most specific location)
        first_part = parts[0]
        
        # Check for parentheses with more specific names
        # "Area B (Westside/Swan Lake/Kalamalka Lake)" -> "Kalamalka Lake"
        paren_match = re.search(r'\(([^)]+)\)', first_part)
        if paren_match:
            # Get content in parentheses and take the last item (most specific)
            paren_content = paren_match.group(1)
            # Split by / to get individual names
            names = [n.strip() for n in paren_content.split('/')]
            if names:
                # Take the last one as it's usually most specific
                specific_name = names[-1]
                # Add city/country for context if available
                if city and city not in specific_name:
                    return f"{specific_name}_{city}"
                elif country and country not in specific_name:
                    return f"{specific_name}_{country}"
                return specific_name
        
        # If first part is generic (Area, District, etc), use city
        generic_prefixes = ['Area ', 'District ', 'Region ', 'County ']
        if any(first_part.startswith(prefix) for prefix in generic_prefixes):
            if city:
                return city
        
        # Use first part if it looks meaningful
        if len(first_part) > 3 and not first_part.isdigit():
            return first_part
        
        # Fallback to city or country
        return city or country
    
    @staticmethod
    def extract_time_suffix(metadata: Dict) -> str:
        """Extract HHMMSS time suffix from capture time (prefers UTC)."""
        date_taken = metadata.get('date_taken_utc') or metadata.get('date_taken')
        if not date_taken:
            return ''
        
        try:
            if isinstance(date_taken, str):
                dt = datetime.fromisoformat(date_taken.replace('Z', '+00:00'))
            else:
                dt = date_taken
            return dt.strftime('%H%M%S')
        except:
            return ''
    
    @staticmethod
    def generate_from_metadata(metadata: Dict, original_filename: str) -> str:
        """
        Generate a meaningful filename from metadata
        
        Args:
            metadata: Image metadata including location, date, etc.
            original_filename: Original filename (for fallback)
            
        Returns:
            New filename (stem only, no extension)
        """
        # Check if original filename is generic
        needs_rename = FilenameGenerator.is_generic_filename(original_filename)
        
        if not needs_rename:
            # Keep original meaningful name
            return Path(original_filename).stem
        
        # Extract location from metadata
        location_dict = metadata.get('location', {})
        if isinstance(location_dict, str):
            # Fallback if location is just a string
            location_name = location_dict
        else:
            location_name = FilenameGenerator.extract_meaningful_location(location_dict)
        
        # Build filename from location
        name_parts = []
        
        if location_name:
            # Slugify the location name
            slug = FilenameGenerator.slugify(location_name, 40)
            name_parts.append(slug)
        
        # Add time-of-day suffix if available
        time_suffix = FilenameGenerator.extract_time_suffix(metadata)
        if time_suffix:
            name_parts.append(time_suffix)
        
        # If no location or time, fallback to date
        if not name_parts:
            date_taken = metadata.get('date_taken_utc') or metadata.get('date_taken')
            if date_taken:
                try:
                    if isinstance(date_taken, str):
                        dt = datetime.fromisoformat(date_taken.replace('Z', '+00:00'))
                    else:
                        dt = date_taken
                    name_parts.append(dt.strftime('%Y%m%d_%H%M%S'))
                except:
                    pass
        
        # If still no name, use original stem
        if not name_parts:
            return Path(original_filename).stem
        
        # Join parts with underscore
        new_name = '_'.join(name_parts)
        
        return new_name
    
    @staticmethod
    def ensure_unique_path(base_path: Path, stem: str, extension: str) -> Path:
        """
        Ensure output path is unique by adding counter if needed
        
        Args:
            base_path: Directory for output
            stem: Filename stem (no extension)
            extension: File extension (with or without dot)
            
        Returns:
            Unique Path object
        """
        if not extension.startswith('.'):
            extension = f'.{extension}'
        
        output_path = base_path / f"{stem}{extension}"
        
        # If path exists, add counter
        counter = 1
        while output_path.exists():
            output_path = base_path / f"{stem}_{counter}{extension}"
            counter += 1
        
        return output_path
