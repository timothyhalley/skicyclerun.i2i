"""
Watermark Applicator
Applies text watermarks to images with configurable styling
"""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
from typing import Dict, Tuple

class WatermarkApplicator:
    def __init__(self, config: Dict):
        self.config = config
        self.watermark_config = config.get('watermark', {})
        self.font_config = self.watermark_config.get('font', {})
        self.position = self.watermark_config.get('position', 'bottom_right')
        self.margin = self.watermark_config.get('margin', {'x': 20, 'y': 20})
    
    def _get_font(self, image_width: int, emoji_compatible: bool = False):
        """Get font with size scaled to image width"""
        base_size = self.font_config.get('size', 24)
        # Scale font size based on image width (base: 1920px)
        scaled_size = int(base_size * (image_width / 1920.0))
        scaled_size = max(12, min(scaled_size, 72))  # Clamp between 12-72
        
        font_family = self.font_config.get('family', 'Asimovian')
        
        # Try fonts in order of preference
        font_paths = []
        
        if emoji_compatible:
            # For emoji/symbols, use Apple Color Emoji
            font_paths = [
                "/System/Library/Fonts/Apple Color Emoji.ttc",
                "/System/Library/Fonts/Supplemental/AppleColorEmoji.ttf"
            ]
        else:
            # For main text, try Asimovian or fallbacks
            font_paths = [
                f"/System/Library/Fonts/{font_family}.ttc",
                f"/Library/Fonts/{font_family}.ttf",
                "/System/Library/Fonts/Supplemental/Courier New.ttf",
                "/System/Library/Fonts/Supplemental/Arial.ttf"
            ]
        
        for font_path in font_paths:
            try:
                font = ImageFont.truetype(font_path, scaled_size)
                return font
            except:
                continue
        
        # Last resort: default font
        return ImageFont.load_default()
    
    def _get_text_position(self, image_size: Tuple[int, int], text_bbox: Tuple[int, int, int, int]) -> Tuple[int, int]:
        """Calculate text position based on configuration"""
        img_width, img_height = image_size
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        
        margin_x = self.margin.get('x', 20)
        margin_y = self.margin.get('y', 20)
        
        if self.position == 'bottom_right':
            x = img_width - text_width - margin_x
            y = img_height - text_height - margin_y
        elif self.position == 'bottom_left':
            x = margin_x
            y = img_height - text_height - margin_y
        elif self.position == 'top_right':
            x = img_width - text_width - margin_x
            y = margin_y
        elif self.position == 'top_left':
            x = margin_x
            y = margin_y
        elif self.position == 'center':
            x = (img_width - text_width) // 2
            y = (img_height - text_height) // 2
        else:
            # Default to bottom_right
            x = img_width - text_width - margin_x
            y = img_height - text_height - margin_y
        
        return (x, y)
    
    def apply_watermark(self, image_path: str, watermark_text: str, output_path: str):
        """Apply watermark to image"""
        # Load image
        image = Image.open(image_path)
        
        # Convert to RGBA if needed for transparency
        if image.mode != 'RGBA':
            image = image.convert('RGBA')
        
        # Create transparent overlay
        overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        
        # Get font
        font = self._get_font(image.width)
        
        # Get text bounding box
        bbox = draw.textbbox((0, 0), watermark_text, font=font)
        
        # Calculate position
        position = self._get_text_position(image.size, bbox)
        
        # Get colors
        text_color = tuple(self.font_config.get('color', [255, 255, 255, 180]))
        stroke_color = tuple(self.font_config.get('stroke_color', [0, 0, 0, 200]))
        stroke_width = self.font_config.get('stroke_width', 2)
        
        # Draw text with stroke (outline)
        draw.text(
            position,
            watermark_text,
            font=font,
            fill=text_color,
            stroke_width=stroke_width,
            stroke_fill=stroke_color,
            embedded_color=True  # Enable emoji color rendering
        )
        
        # Composite overlay onto original image
        watermarked = Image.alpha_composite(image, overlay)
        
        # Convert back to RGB if output format doesn't support alpha
        output_path_obj = Path(output_path)
        if output_path_obj.suffix.lower() in ['.jpg', '.jpeg']:
            watermarked = watermarked.convert('RGB')
        
        # Save
        output_path_obj.parent.mkdir(parents=True, exist_ok=True)
        watermarked.save(output_path)
        
        return output_path
