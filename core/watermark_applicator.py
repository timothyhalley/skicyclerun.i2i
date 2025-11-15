"""Watermark Applicator
Applies text watermarks to images with configurable styling.

Enhancements (shrink-to-fit):
- If configured fit_mode == 'shrink_to_fit', we will iteratively reduce
    the font size until the watermark text fits within
    (image_width * max_width_percent) minus horizontal margins.
- Config keys supported (under watermark.font):
        size:        starting (desired) size
        min_size:    lowest size we will allow (default 20)
        max_width_percent: percentage (0-100) of image width allowed (default 65)
        fit_mode:    'shrink_to_fit' or 'none'
"""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
from typing import Dict, Tuple
import sys

class WatermarkApplicator:
    def __init__(self, config: Dict):
        self.config = config
        self.watermark_config = config.get('watermark', {})
        self.font_config = self.watermark_config.get('font', {})
        self.position = self.watermark_config.get('position', 'bottom_right')
        self.margin = self.watermark_config.get('margin', {'x': 20, 'y': 20})
        # Extended config
        self.fit_mode = self.font_config.get('fit_mode', 'shrink_to_fit')
        self.min_size = int(self.font_config.get('min_size', 20))
        self.max_width_percent = float(self.font_config.get('max_width_percent', 65))
        # Debug / verbose control (default off)
        self.debug = bool(self.watermark_config.get('debug', False))
    
    def _get_font(self, font_size: int):
        """Load a font of a specific size using fallback chain."""
        # Try multiple font options in order of preference
        font_paths = [
            "/System/Library/Fonts/Courier New Bold.ttf",
            "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
            "/System/Library/Fonts/Supplemental/Courier New.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf"
        ]
        
        for font_path in font_paths:
            try:
                font = ImageFont.truetype(font_path, font_size)
                return font
            except:
                continue
        
        # Last resort: default font
        return ImageFont.load_default()

    def _shrink_to_fit(self, draw: ImageDraw.ImageDraw, text: str, image_width: int) -> ImageFont.FreeTypeFont:
        """Shrink font size until text fits allowed width or min_size reached."""
        desired_size = int(self.font_config.get('size', 32))
        font_size = desired_size
        font = self._get_font(font_size)
        margin_x = self.margin.get('x', 20)
        allowed_width = int(image_width * (self.max_width_percent / 100.0)) - margin_x
        if allowed_width <= 0:
            allowed_width = image_width - margin_x
        while font_size > self.min_size:
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            if text_width <= allowed_width:
                break
            font_size -= 1
            font = self._get_font(font_size)
        if self.debug:
            print(f"[WatermarkApplicator] fit_mode=shrink_to_fit desired={desired_size} final={font_size} allowed_width={allowed_width}", file=sys.stderr)
        return font
    
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
        """Apply watermark to image with optional shrink-to-fit behavior."""
        # Load image
        image = Image.open(image_path)
        
        # Convert to RGBA if needed for transparency
        if image.mode != 'RGBA':
            image = image.convert('RGBA')
        
        # Create transparent overlay
        overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        
        # Get font (fitting if enabled)
        if self.fit_mode == 'shrink_to_fit':
            font = self._shrink_to_fit(draw, watermark_text, image.width)
        else:
            font_size = int(self.font_config.get('size', 32))
            font = self._get_font(font_size)
        
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
            embedded_color=True
        )
        final_bbox = draw.textbbox((0, 0), watermark_text, font=font)
        final_width = final_bbox[2] - final_bbox[0]
        if self.debug:
            print(f"[WatermarkApplicator] final_text_width={final_width} image_width={image.width}", file=sys.stderr)
        
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
