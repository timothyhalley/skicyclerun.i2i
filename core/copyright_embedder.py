"""
Copyright Metadata Embedder
Embeds comprehensive copyright and metadata information into image EXIF
"""
from PIL import Image
from PIL.ExifTags import TAGS
import piexif
from typing import Dict, Optional
from datetime import datetime


class CopyrightEmbedder:
    """Embeds copyright metadata into image EXIF"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.copyright_config = config.get('copyright', {})
        self.owner = self.copyright_config.get('owner', 'SkiCycleRun')
        self.website = self.copyright_config.get('website', 'https://skicyclerun.com')
        self.rights_statement = self.copyright_config.get('rights_statement', 
            'Copyright © {year} {owner}. All rights reserved.')
    
    def generate_copyright_text(self, metadata: Dict) -> str:
        """Generate copyright text from metadata"""
        year = datetime.now().year
        
        # Try to get year from date_taken
        date_taken = metadata.get('date_taken') or metadata.get('exif', {}).get('date_time_original')
        if date_taken:
            try:
                if isinstance(date_taken, str):
                    dt = datetime.fromisoformat(date_taken.replace('Z', '+00:00'))
                    year = dt.year
            except:
                pass
        
        return self.rights_statement.format(year=year, owner=self.owner)
    
    def generate_description(self, metadata: Dict) -> str:
        """Generate comprehensive description from metadata"""
        parts = []
        
        # Location information
        location = metadata.get('location_formatted', '')
        if location and location != 'Unknown Location':
            parts.append(f"Location: {location}")
        
        # POI/Landmark if available
        landmarks = metadata.get('landmarks', [])
        if landmarks and len(landmarks) > 0:
            landmark = landmarks[0]
            landmark_name = landmark.get('name', '')
            if landmark_name:
                parts.append(f"Near: {landmark_name}")
        
        # GPS Coordinates
        gps_coords = metadata.get('gps_coordinates') or metadata.get('gps')
        if gps_coords:
            lat = gps_coords.get('lat')
            lon = gps_coords.get('lon')
            if lat is not None and lon is not None:
                parts.append(f"GPS: {lat:.6f}, {lon:.6f}")
        
        # Date taken
        date_taken = metadata.get('date_taken') or metadata.get('exif', {}).get('date_time_original')
        if date_taken:
            try:
                if isinstance(date_taken, str):
                    dt = datetime.fromisoformat(date_taken.replace('Z', '+00:00'))
                    parts.append(f"Captured: {dt.strftime('%B %d, %Y at %I:%M %p')}")
            except:
                parts.append(f"Captured: {date_taken}")
        
        # Camera information
        exif = metadata.get('exif', {})
        camera_make = exif.get('camera_make', '')
        camera_model = exif.get('camera_model', '')
        if camera_make or camera_model:
            camera = f"{camera_make} {camera_model}".strip()
            parts.append(f"Camera: {camera}")
        
        lens_model = exif.get('lens_model', '')
        if lens_model:
            parts.append(f"Lens: {lens_model}")
        
        return " | ".join(parts) if parts else "SkiCycleRun Photography"
    
    def generate_keywords(self, metadata: Dict) -> list:
        """Generate keywords from metadata"""
        keywords = ['SkiCycleRun']
        
        # Add location-based keywords
        location = metadata.get('location', {})
        if location:
            city = location.get('city', '')
            state = location.get('state', '')
            country = location.get('country', '')
            
            if city:
                keywords.append(city)
            if state:
                keywords.append(state)
            if country:
                keywords.append(country)
        
        # Add landmark keywords
        landmarks = metadata.get('landmarks', [])
        for landmark in landmarks[:3]:  # Max 3 landmarks
            name = landmark.get('name', '')
            if name:
                keywords.append(name)
        
        # Add activity-based keywords
        keywords.extend(['Photography', 'Travel', 'Adventure'])
        
        return keywords
    
    def embed_copyright_metadata(self, image_path: str, output_path: str, metadata: Dict) -> bool:
        """
        Embed comprehensive copyright metadata into image EXIF
        
        Args:
            image_path: Path to source image
            output_path: Path to output image with embedded metadata
            metadata: Dictionary with extracted metadata
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Load image
            img = Image.open(image_path)
            
            # Load existing EXIF or create new
            try:
                exif_dict = piexif.load(image_path)
            except:
                exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
            
            # Generate copyright text and description
            copyright_text = self.generate_copyright_text(metadata)
            description = self.generate_description(metadata)
            keywords = self.generate_keywords(metadata)
            
            # Embed into EXIF
            # 0th IFD (Image File Directory) - Main image tags
            exif_dict["0th"][piexif.ImageIFD.Copyright] = copyright_text.encode('utf-8')
            exif_dict["0th"][piexif.ImageIFD.Artist] = self.owner.encode('utf-8')
            exif_dict["0th"][piexif.ImageIFD.ImageDescription] = description.encode('utf-8')
            
            # XPKeywords (Windows/Adobe compatible)
            if keywords:
                # XPKeywords needs UTF-16LE encoding
                keywords_str = ';'.join(keywords)
                exif_dict["0th"][piexif.ImageIFD.XPKeywords] = keywords_str.encode('utf-16le')
            
            # Add website to UserComment if available
            if self.website:
                exif_dict["Exif"][piexif.ExifIFD.UserComment] = self.website.encode('utf-8')
            
            # Convert to bytes and save
            exif_bytes = piexif.dump(exif_dict)
            img.save(output_path, exif=exif_bytes)
            
            return True
            
        except Exception as e:
            print(f"Warning: Could not embed copyright metadata in {image_path}: {e}")
            # Fallback: just copy the image without EXIF modification
            try:
                img = Image.open(image_path)
                img.save(output_path)
            except:
                pass
            return False
    
    def verify_copyright_metadata(self, image_path: str) -> Dict:
        """Verify copyright metadata was embedded correctly"""
        try:
            exif_dict = piexif.load(image_path)
            
            return {
                'copyright': exif_dict["0th"].get(piexif.ImageIFD.Copyright, b'').decode('utf-8', errors='ignore'),
                'artist': exif_dict["0th"].get(piexif.ImageIFD.Artist, b'').decode('utf-8', errors='ignore'),
                'description': exif_dict["0th"].get(piexif.ImageIFD.ImageDescription, b'').decode('utf-8', errors='ignore'),
                'keywords': exif_dict["0th"].get(piexif.ImageIFD.XPKeywords, b'').decode('utf-16le', errors='ignore'),
                'user_comment': exif_dict["Exif"].get(piexif.ExifIFD.UserComment, b'').decode('utf-8', errors='ignore')
            }
        except Exception as e:
            print(f"Warning: Could not verify copyright metadata in {image_path}: {e}")
            return {}
