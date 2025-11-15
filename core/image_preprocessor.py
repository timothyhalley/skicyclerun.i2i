"""
Image Preprocessor
Scales, optimizes, and prepares images for LoRA processing
Maintains aspect ratios and catalogs all metadata
"""
from PIL import Image, ImageOps
from pathlib import Path
from typing import Dict, Tuple, Optional
import json
from datetime import datetime
from utils.time_utils import utc_now_iso_z


class ImagePreprocessor:
    def __init__(self, config: Dict):
        self.config = config
        self.preprocess_config = config.get('preprocessing', {})
        self.max_dimension = self.preprocess_config.get('max_dimension', 2048)
        self.output_format = self.preprocess_config.get('format', 'webp')
        self.quality = self.preprocess_config.get('quality', 90)
        self.preserve_aspect = self.preprocess_config.get('preserve_aspect_ratio', True)
        self.optimize = self.preprocess_config.get('optimize', True)
        self.processed_metadata = {}
        
    def calculate_new_dimensions(self, original_size: Tuple[int, int]) -> Tuple[int, int]:
        """Calculate new dimensions while preserving aspect ratio"""
        width, height = original_size
        
        # If image is already smaller than max, keep original size
        if width <= self.max_dimension and height <= self.max_dimension:
            return (width, height)
        
        # Scale down to fit within max_dimension
        if width > height:
            # Landscape
            new_width = self.max_dimension
            new_height = int(height * (self.max_dimension / width))
        else:
            # Portrait or square
            new_height = self.max_dimension
            new_width = int(width * (self.max_dimension / height))
        
        # Ensure dimensions are multiples of 8 (FLUX requirement)
        new_width = (new_width // 8) * 8
        new_height = (new_height // 8) * 8
        
        return (new_width, new_height)
    
    def preprocess_image(self, input_path: str, output_path: str, existing_metadata: Optional[Dict] = None) -> Dict:
        """
        Preprocess a single image: scale, optimize, and preserve metadata
        
        Args:
            input_path: Path to source image
            output_path: Path for preprocessed output
            existing_metadata: Optional metadata from geo_extractor
            
        Returns:
            Dict with processing metadata
        """
        try:
            # Load image
            image = Image.open(input_path)
            original_size = image.size
            original_format = image.format
            original_mode = image.mode
            
            # Preserve EXIF data
            exif_data = image.info.get('exif')
            
            # Auto-orient based on EXIF orientation
            image = ImageOps.exif_transpose(image)
            
            # Convert to RGB if needed (for JPEG/WebP compatibility)
            if image.mode in ('RGBA', 'LA', 'P'):
                # Handle transparency
                if self.output_format.lower() in ['jpg', 'jpeg']:
                    # Create white background for JPEG
                    background = Image.new('RGB', image.size, (255, 255, 255))
                    if image.mode == 'P':
                        image = image.convert('RGBA')
                    background.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
                    image = background
                elif image.mode == 'P':
                    image = image.convert('RGB')
            elif image.mode != 'RGB':
                image = image.convert('RGB')
            
            # Calculate new dimensions
            new_size = self.calculate_new_dimensions(original_size)
            
            # Resize if needed
            if new_size != original_size:
                image = image.resize(new_size, Image.Resampling.LANCZOS)
            
            # Prepare output path
            output_path_obj = Path(output_path)
            output_path_obj.parent.mkdir(parents=True, exist_ok=True)
            
            # Save with optimization
            save_kwargs = {
                'quality': self.quality,
                'optimize': self.optimize
            }
            
            # Add EXIF data back if available
            if exif_data:
                save_kwargs['exif'] = exif_data
            
            # Format-specific options
            if self.output_format.lower() == 'webp':
                save_kwargs['method'] = 6  # Best quality
            elif self.output_format.lower() in ['jpg', 'jpeg']:
                save_kwargs['progressive'] = True
                save_kwargs['subsampling'] = 0  # Best quality
            
            image.save(output_path, format=self.output_format.upper(), **save_kwargs)
            
            # Calculate file size reduction
            input_size = Path(input_path).stat().st_size
            output_size = Path(output_path).stat().st_size
            size_reduction = ((input_size - output_size) / input_size) * 100 if input_size > 0 else 0
            
            # Build processing metadata
            processing_metadata = {
                'input_path': str(input_path),
                'output_path': str(output_path),
                'original_size': {'width': original_size[0], 'height': original_size[1]},
                'processed_size': {'width': new_size[0], 'height': new_size[1]},
                'original_format': original_format,
                'output_format': self.output_format,
                'original_mode': original_mode,
                'original_file_size': input_size,
                'processed_file_size': output_size,
                'size_reduction_percent': round(size_reduction, 2),
                'processed_timestamp': utc_now_iso_z(),
                'quality': self.quality
            }
            
            # Merge with existing metadata if provided
            if existing_metadata:
                processing_metadata.update(existing_metadata)
            
            return processing_metadata
            
        except Exception as e:
            raise Exception(f"Failed to preprocess {input_path}: {e}")
    
    def preprocess_directory(self, input_dir: str, output_dir: str, metadata_catalog: Optional[Dict] = None) -> Dict:
        """
        Preprocess all images in a directory
        
        Args:
            input_dir: Source directory
            output_dir: Output directory
            metadata_catalog: Optional existing metadata from geo_extractor
            
        Returns:
            Dict of all processed image metadata
        """
        input_path = Path(input_dir)
        output_path = Path(output_dir)
        
        if not input_path.exists():
            raise FileNotFoundError(f"Input directory not found: {input_dir}")
        
        # Find all images
        image_extensions = ['*.jpg', '*.jpeg', '*.png', '*.webp', '*.JPG', '*.JPEG', '*.PNG']
        image_files = []
        for ext in image_extensions:
            image_files.extend(list(input_path.glob(f'**/{ext}')))
        
        if not image_files:
            print(f"⚠️  No images found in {input_dir}")
            return {}
        
        print(f"📊 Found {len(image_files)} images to preprocess")
        
        processed_catalog = {}
        success_count = 0
        error_count = 0
        
        for idx, image_file in enumerate(image_files, 1):
            try:
                # Preserve folder structure
                relative_path = image_file.relative_to(input_path)
                
                # Change extension to output format
                output_file = output_path / relative_path.with_suffix(f'.{self.output_format}')
                
                # Check if already preprocessed
                if output_file.exists():
                    # Check metadata catalog to see if this was already processed
                    if metadata_catalog:
                        existing_entry = metadata_catalog.get(str(output_file))
                        if existing_entry and 'processed_size' in existing_entry:
                            # Already preprocessed, add to catalog and skip
                            processed_catalog[str(output_file)] = existing_entry
                            success_count += 1
                            continue
                
                # Get existing metadata if available
                existing_meta = None
                if metadata_catalog:
                    existing_meta = metadata_catalog.get(str(image_file))
                
                # Preprocess image
                metadata = self.preprocess_image(
                    str(image_file),
                    str(output_file),
                    existing_meta
                )
                
                processed_catalog[str(output_file)] = metadata
                success_count += 1
                
                # Progress logging
                if idx % 10 == 0:
                    print(f"  Processed {idx}/{len(image_files)} images...")
                
            except Exception as e:
                print(f"  ❌ Error processing {image_file.name}: {e}")
                error_count += 1
        
        print(f"✅ Preprocessing complete: {success_count} successful, {error_count} errors")
        
        # Calculate statistics
        if processed_catalog:
            # Use safe access because some pre-existing entries may not include size fields
            total_input_size = sum((m.get('original_file_size') or 0) for m in processed_catalog.values())
            total_output_size = sum((m.get('processed_file_size') or 0) for m in processed_catalog.values())
            total_reduction = ((total_input_size - total_output_size) / total_input_size) * 100 if total_input_size > 0 else 0
            
            print(f"📉 Total size reduction: {total_reduction:.2f}% ({total_input_size / 1024 / 1024:.2f} MB → {total_output_size / 1024 / 1024:.2f} MB)")
        
        self.processed_metadata = processed_catalog
        return processed_catalog
    
    def save_catalog(self, catalog_path: str):
        """Save processing catalog to JSON"""
        catalog_file = Path(catalog_path)
        catalog_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(catalog_file, 'w') as f:
            json.dump(self.processed_metadata, f, indent=2)
        
        print(f"💾 Saved preprocessing catalog: {catalog_path}")
    
    def load_catalog(self, catalog_path: str) -> Dict:
        """Load existing processing catalog"""
        catalog_file = Path(catalog_path)
        
        if not catalog_file.exists():
            return {}
        
        try:
            with open(catalog_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️  Could not load catalog: {e}")
            return {}
