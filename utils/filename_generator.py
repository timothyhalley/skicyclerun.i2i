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
        
        # Build new name from metadata
        name_parts = []
        
        # Extract location components
        location = metadata.get('location', {})
        if isinstance(location, dict):
            location_str = location.get('formatted', '')
        else:
            location_str = str(location)
        
        loc_components = FilenameGenerator.extract_location_components(location_str)
        
        # Add city if available
        if loc_components['city']:
            name_parts.append(FilenameGenerator.slugify(loc_components['city'], 30))
        
        # Add region if available and different from city
        if loc_components['region'] and loc_components['region'] != loc_components['city']:
            name_parts.append(FilenameGenerator.slugify(loc_components['region'], 20))
        
        # If no location, try to use date
        if not name_parts:
            date_taken = metadata.get('date_taken')
            if date_taken:
                try:
                    if isinstance(date_taken, str):
                        dt = datetime.fromisoformat(date_taken.replace('Z', '+00:00'))
                    else:
                        dt = date_taken
                    name_parts.append(dt.strftime('%Y%m%d'))
                except:
                    pass
        
        # If still no name, use original stem
        if not name_parts:
            return Path(original_filename).stem
        
        # Join parts
        new_name = '_'.join(name_parts)
        
        # Add original numeric suffix if it exists (to avoid duplicates)
        original_stem = Path(original_filename).stem
        suffix_match = re.search(r'(\d{3,})$', original_stem)
        if suffix_match:
            new_name = f"{new_name}_{suffix_match.group(1)}"
        
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
