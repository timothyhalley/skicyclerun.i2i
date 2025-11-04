import numpy as np
import os
from PIL import Image, ImageFilter, ImageEnhance
from diffusers.utils import load_image
from utils.logger import logInfo

def rescale_image(image, max_dim):
    w, h = image.size
    scale = min(max_dim / w, max_dim / h)
    new_w = int(w * scale)
    new_h = int(h * scale)
    
    # FLUX model has specific dimension requirements
    # Try multiples of 16 (common for diffusion models)
    new_w = round(new_w / 16) * 16
    new_h = round(new_h / 16) * 16
    
    # Ensure reasonable minimum size but not too large
    new_w = max(new_w, 256)
    new_h = max(new_h, 256)
    
    # Cap at 512 to prevent memory issues
    new_w = min(new_w, 512)
    new_h = min(new_h, 512)
    
    new_size = (new_w, new_h)
    logInfo(f"🔧 Scaled image: {w}×{h} → {new_w}×{new_h} (multiple of 16, capped at 512)")
    return image.resize(new_size, Image.LANCZOS)

def preprocess_image(image, config):
    if config.get("cleanup", False):
        image = image.convert("RGB")
        image = image.filter(ImageFilter.MedianFilter(size=3))
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(1.2)

    if config.get("face_detection", False):
        try:
            import mediapipe as mp
            mp_face = mp.solutions.face_detection.FaceDetection(model_selection=1)
            results = mp_face.process(np.array(image))
            if not results.detections:
                logInfo("⚠️ No face detected.")
        except ImportError:
            logInfo("⚠️ mediapipe not installed.")
    return image

def load_and_prepare_image(path, max_dim, preprocess_cfg):
    """Load and prepare image for FLUX inference.
    
    Preserve aspect ratio - resize longest dimension to max_dim.
    FLUX will handle the rest.
    """
    image = load_image(path)
    
    # Get original dimensions
    orig_width, orig_height = image.size
    
    # Calculate new dimensions preserving aspect ratio
    # Resize so longest dimension is max_dim (typically 1024)
    if orig_width > orig_height:
        new_width = max_dim
        new_height = int(orig_height * (max_dim / orig_width))
    else:
        new_height = max_dim
        new_width = int(orig_width * (max_dim / orig_height))
    
    # Round to multiples of 16 (FLUX requirement)
    new_width = round(new_width / 16) * 16
    new_height = round(new_height / 16) * 16
    
    image = image.resize((new_width, new_height), Image.LANCZOS)
    logInfo(f"🖼️  Resized image: {orig_width}×{orig_height} → {new_width}×{new_height} (aspect ratio preserved)")
    
    # Optional preprocessing if enabled
    if preprocess_cfg.get("enabled", False):
        image = preprocess_image(image, preprocess_cfg)
    
    return image