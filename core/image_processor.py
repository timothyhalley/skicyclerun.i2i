import numpy as np
import logging
import os
from PIL import Image, ImageFilter, ImageEnhance
from diffusers.utils import load_image

logging.basicConfig(level=logging.INFO)

def rescale_image(image, max_dim):
    w, h = image.size
    scale = min(max_dim / w, max_dim / h)
    new_size = (int(w * scale), int(h * scale))
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
                logging.info("⚠️ No face detected.")
        except ImportError:
            logging.info("⚠️ mediapipe not installed.")
    return image

def load_and_prepare_image(path, max_dim, preprocess_cfg):
    image = load_image(path)
    image = rescale_image(image, max_dim)
    if preprocess_cfg.get("enabled", False):
        image = preprocess_image(image, preprocess_cfg)
    return image