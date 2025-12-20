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
        # First, check if custom font path is specified in config
        custom_font_path = self.font_config.get('path')
        if custom_font_path:
            # Support both absolute and relative paths
            if not Path(custom_font_path).is_absolute():
                # Relative to project root
                custom_font_path = Path(__file__).parent.parent / custom_font_path
            try:
                font = ImageFont.truetype(str(custom_font_path), font_size)
                return font
            except Exception as e:
                print(f"[WatermarkApplicator] Failed to load custom font {custom_font_path}: {e}", file=sys.stderr)
                print(f"[WatermarkApplicator] Falling back to system fonts", file=sys.stderr)
        
        # Try multiple system font options in order of preference
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
    
    def _wrap_text_smart(self, text: str, draw, font, max_width: int) -> list:
        """
        Intelligently wrap text at natural break points (commas, 'and', 'near').
        
        Args:
            text: Text to wrap
            draw: PIL ImageDraw object
            font: Font to use for measuring
            max_width: Maximum width in pixels
            
        Returns:
            List of text lines
        """
        # Try breaking at natural points (prepositions, conjunctions, punctuation)
        break_points = [', ', ' and ', ' near ', ' - ', ' in ', ' at ', ' with ', ' of ', ' against ', ' for ', ' to ', ' from ']
        
        # Find all possible break positions
        breaks = []
        for bp in break_points:
            pos = 0
            while True:
                pos = text.find(bp, pos)
                if pos == -1:
                    break
                breaks.append((pos, pos + len(bp), bp))
                pos += len(bp)
        
        # Sort by position
        breaks.sort(key=lambda x: x[0])
        
        if not breaks:
            # No natural breaks, force word wrap
            return self._wrap_text_words(text, draw, font, max_width)
        
        # Try to find best break point
        lines = []
        start = 0
        
        for break_pos, break_end, break_str in breaks:
            # Check if text from start to break point fits
            chunk = text[start:break_pos].strip()
            if not chunk:
                continue
                
            bbox = draw.textbbox((0, 0), chunk, font=font)
            chunk_width = bbox[2] - bbox[0]
            
            if chunk_width <= max_width:
                # This chunk fits, check if adding more would still fit
                remaining = text[break_end:].strip()
                full_line = chunk + (break_str if remaining else '')
                bbox = draw.textbbox((0, 0), full_line, font=font)
                if (bbox[2] - bbox[0]) > max_width:
                    # Adding more would be too wide, break here
                    lines.append(chunk)
                    start = break_end
            else:
                # This chunk is too wide, need to break earlier
                if lines:
                    # We already have some lines, continue with what we have
                    remaining = text[start:].strip()
                    if remaining:
                        # Force wrap the remaining text
                        lines.extend(self._wrap_text_words(remaining, draw, font, max_width))
                    return lines
                else:
                    # First chunk is too wide, force word wrap entire text
                    return self._wrap_text_words(text, draw, font, max_width)
        
        # Add any remaining text
        remaining = text[start:].strip()
        if remaining:
            lines.append(remaining)
        
        return lines if lines else [text]
    
    def _wrap_text_words(self, text: str, draw, font, max_width: int) -> list:
        """
        Force wrap text by words when no natural breaks work.
        
        Args:
            text: Text to wrap
            draw: PIL ImageDraw object
            font: Font to use for measuring
            max_width: Maximum width in pixels
            
        Returns:
            List of text lines
        """
        words = text.split()
        lines = []
        current_line = []
        
        for word in words:
            # Handle hyphenated words by checking if they need to be split
            if '-' in word and len(word) > 15:
                # Check if hyphenated word is too long
                bbox = draw.textbbox((0, 0), word, font=font)
                if (bbox[2] - bbox[0]) > max_width:
                    # Split on hyphen and treat as separate words
                    hyphen_parts = word.split('-')
                    for i, part in enumerate(hyphen_parts):
                        if i < len(hyphen_parts) - 1:
                            part = part + '-'  # Keep hyphen with first part
                        test_line = ' '.join(current_line + [part])
                        bbox = draw.textbbox((0, 0), test_line, font=font)
                        
                        if (bbox[2] - bbox[0]) <= max_width:
                            current_line.append(part)
                        else:
                            if current_line:
                                lines.append(' '.join(current_line))
                                current_line = [part]
                            else:
                                lines.append(part)
                    continue
            
            test_line = ' '.join(current_line + [word])
            bbox = draw.textbbox((0, 0), test_line, font=font)
            
            if (bbox[2] - bbox[0]) <= max_width:
                current_line.append(word)
            else:
                if current_line:
                    lines.append(' '.join(current_line))
                    current_line = [word]
                    
                    # Check if this single word is too long
                    bbox = draw.textbbox((0, 0), word, font=font)
                    if (bbox[2] - bbox[0]) > max_width:
                        # Word itself is too long, force it on its own line
                        lines.append(word)
                        current_line = []
                else:
                    # First word is too long, add it anyway
                    lines.append(word)
        
        if current_line:
            lines.append(' '.join(current_line))
        
        return lines if lines else [text]
    
    def apply_watermark(self, image_path: str, line1_text: str, line2_text: str, output_path: str):
        """
        Apply two-line watermark to image.
        
        Args:
            image_path: Path to source image
            line1_text: Watermark text (from LLM)
            line2_text: Location + copyright (assembled by pipeline)
            output_path: Where to save watermarked image
        """
        # Load image
        image = Image.open(image_path)
        
        # Convert to RGBA if needed for transparency
        if image.mode != 'RGBA':
            image = image.convert('RGBA')
        
        # Create transparent overlay
        overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        
        # Apply two-line watermark
        self._apply_two_line_watermark(draw, image.size, line1_text, line2_text)
        
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
    
    def _apply_two_line_watermark(self, draw, image_size, line1_text: str, line2_text: str):
        """
        Apply two-line watermark to image.
        
        Args:
            draw: ImageDraw object
            image_size: (width, height) tuple
            line1_text: Watermark text (from LLM)
            line2_text: Location + copyright (assembled by pipeline)
        """
        # Get config for both lines
        loc_config = self.watermark_config.get('location_line', {})
        copy_config = self.watermark_config.get('copyright_line', {})
        line_spacing = self.watermark_config.get('line_spacing', 8)
        
        # LINE 1: LLM watermark (passed in)
        location_text = line1_text.strip() if line1_text else None
        
        # LINE 2: Location + copyright (passed in)
        copyright_text = line2_text.strip()
        
        # Get fonts and sizing
        loc_size = loc_config.get('font_size', 36)
        copy_size = copy_config.get('font_size', 18)
        max_width = int(image_size[0] * self.font_config.get('max_width_percent', 80) / 100)
        margin_x = self.margin.get('x', 50)
        margin_y = self.margin.get('y', 40)
        
        # Process LINE 1 (LLM watermark) if available
        loc_lines = []
        loc_line_heights = []
        loc_total_height = 0
        
        if location_text:
            absolute_min_size = 16
            loc_font = self._get_font(loc_size)
            
            # Try shrinking font to fit
            while loc_size > absolute_min_size:
                bbox = draw.textbbox((0, 0), location_text, font=loc_font)
                if (bbox[2] - bbox[0]) <= max_width:
                    break
                loc_size -= 1
                loc_font = self._get_font(loc_size)
            
            # Check final width and wrap if needed
            bbox = draw.textbbox((0, 0), location_text, font=loc_font)
            if (bbox[2] - bbox[0]) > max_width:
                # Still too wide after shrinking - must wrap to multiple lines
                loc_lines = self._wrap_text_smart(location_text, draw, loc_font, max_width)
            else:
                # Fits on single line
                loc_lines = [location_text]
            
            # Measure each line
            for line in loc_lines:
                bbox = draw.textbbox((0, 0), line, font=loc_font)
                loc_line_heights.append(bbox[3] - bbox[1])
            
            loc_total_height = sum(loc_line_heights) + (len(loc_lines) - 1) * (line_spacing // 2)
        
        # Process LINE 2 (Copyright)
        copy_font = self._get_font(copy_size)
        copy_bbox = draw.textbbox((0, 0), copyright_text, font=copy_font)
        copy_width = copy_bbox[2] - copy_bbox[0]
        copy_height = copy_bbox[3] - copy_bbox[1]
        
        # Calculate total height and position
        total_height = loc_total_height + (line_spacing if location_text else 0) + copy_height
        base_y = image_size[1] - total_height - margin_y
        
        # Draw LINE 1 (LLM watermark) if available
        loc_y = base_y
        if location_text and loc_lines:
            loc_color = tuple(loc_config.get('color', [255, 255, 255, 220]))
            loc_stroke = tuple(loc_config.get('stroke_color', [0, 0, 0, 255]))
            loc_stroke_width = loc_config.get('stroke_width', 3)
            
            for i, line in enumerate(loc_lines):
                bbox = draw.textbbox((0, 0), line, font=loc_font)
                line_width = bbox[2] - bbox[0]
                loc_x = image_size[0] - line_width - margin_x
                
                draw.text((loc_x, loc_y), line, font=loc_font, fill=loc_color,
                         stroke_width=loc_stroke_width, stroke_fill=loc_stroke, embedded_color=True)
                
                loc_y += loc_line_heights[i] + (line_spacing // 2 if i < len(loc_lines) - 1 else 0)
            
            loc_y += line_spacing
        
        # Draw LINE 2 (Copyright)
        copy_x = image_size[0] - copy_width - margin_x
        copy_y = loc_y
        
        copy_color = tuple(copy_config.get('color', [255, 255, 255, 180]))
        copy_stroke = tuple(copy_config.get('stroke_color', [0, 0, 0, 200]))
        copy_stroke_width = copy_config.get('stroke_width', 2)
        
        draw.text((copy_x, copy_y), copyright_text, font=copy_font, fill=copy_color,
                 stroke_width=copy_stroke_width, stroke_fill=copy_stroke, embedded_color=True)
