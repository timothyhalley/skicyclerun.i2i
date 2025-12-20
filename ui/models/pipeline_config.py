"""
Pipeline Configuration Model
Parses pipeline_config.json and provides available stages, flags, and command building
"""
import json
from pathlib import Path
from typing import List, Dict, Optional


class PipelineConfig:
    
    PREFERENCES_FILE = ".ui_preferences.json"
    """Model for pipeline configuration and command building"""
    
    # All available stages in order
    AVAILABLE_STAGES = [
        "export",
        "cleanup", 
        "metadata_extraction",
        "llm_image_analysis",
        "preprocessing",
        "lora_processing",
        "post_lora_watermarking",
        "s3_deployment"
    ]
    
    # Stage descriptions for UI tooltips
    STAGE_DESCRIPTIONS = {
        "export": "Export photos from Apple Photos app",
        "cleanup": "Archive old outputs and remove temp files",
        "metadata_extraction": "Extract EXIF, GPS, geocoding, and POI data",
        "llm_image_analysis": "Analyze images with LLM (6-stage Ollama pipeline)",
        "preprocessing": "Scale and optimize images for LoRA processing",
        "lora_processing": "Apply LoRA style transformations",
        "post_lora_watermarking": "Apply watermarks to processed images",
        "s3_deployment": "Deploy final images to S3 bucket"
    }
    
    # Available command-line flags
    AVAILABLE_FLAGS = {
        "cache_only_geocode": {
            "type": "bool",
            "description": "Use geocoding cache only (no network calls)",
            "default": False
        },
        "force_llm_reanalysis": {
            "type": "bool", 
            "description": "Force LLM image analysis to re-run",
            "default": False
        },
        "force_watermark": {
            "type": "bool",
            "description": "Force watermarking to re-process",
            "default": False
        },
        "verbose": {
            "type": "bool",
            "description": "Enable verbose output to terminal",
            "default": False
        },
        "debug": {
            "type": "bool",
            "description": "Enable debug mode - saves LLM prompts",
            "default": False
        },
        "debug_prompt": {
            "type": "bool",
            "description": "Save Stage 5 & 6 prompts to logs/ folder",
            "default": False
        },
        "force_clean": {
            "type": "bool",
            "description": "Force cleanup even without export stage",
            "default": False
        },
        "yes": {
            "type": "bool",
            "description": "Skip interactive confirmation prompts",
            "default": True  # Default True for UI to avoid hanging
        }
    }
    
    def __init__(self, config_path: str = "config/pipeline_config.json"):
        """Initialize with config file path"""
        self.config_path = Path(config_path)
        self.config_data = self._load_config()
        
    def _load_config(self) -> Dict:
        """Load pipeline configuration from JSON"""
        try:
            with open(self.config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not load config: {e}")
            return {}
    
    def get_enabled_stages(self) -> List[str]:
        """Get list of stages enabled in config"""
        return self.config_data.get('pipeline', {}).get('stages', [])
    
    def is_stage_enabled(self, stage: str) -> bool:
        """Check if a specific stage is enabled in config"""
        return stage in self.get_enabled_stages()
    
    def build_command(self, 
                     stages: Optional[List[str]] = None,
                     flags: Optional[Dict[str, bool]] = None,
                     config_path: Optional[str] = None) -> List[str]:
        """
        Build command-line arguments for pipeline.py
        
        Args:
            stages: List of stages to run (None = all enabled)
            flags: Dict of flag_name -> enabled/disabled
            config_path: Path to config file (None = default)
            
        Returns:
            List of command arguments
        """
        cmd = ["python3", "pipeline.py"]
        
        # Add config path if specified
        if config_path:
            cmd.extend(["--config", config_path])
        
        # Add stages if specified
        if stages:
            cmd.append("--stages")
            cmd.extend(stages)
        
        # Add flags
        if flags:
            for flag_name, enabled in flags.items():
                if enabled and flag_name in self.AVAILABLE_FLAGS:
                    # Convert flag name to CLI format (snake_case -> kebab-case)
                    cli_flag = flag_name.replace('_', '-')
                    cmd.append(f"--{cli_flag}")
        
        return cmd
    
    def get_command_string(self,
                          stages: Optional[List[str]] = None,
                          flags: Optional[Dict[str, bool]] = None,
                          config_path: Optional[str] = None) -> str:
        """
        Build command string for display/copying
        
        Returns:
            Human-readable command string
        """
        cmd = self.build_command(stages, flags, config_path)
        return " ".join(cmd)    
    def save_preferences(self, stages: List[str], flags: Dict[str, bool], window_position: Dict = None):
        """
        Save current UI selections to preferences file
        
        Args:
            stages: List of selected stage names
            flags: Dict of flag_name -> enabled
            window_position: Optional dict with x/y window position
        """
        prefs_path = Path(self.config_path).parent.parent / self.PREFERENCES_FILE
        
        # Load existing preferences to preserve window_position if not provided
        existing_prefs = {}
        if prefs_path.exists():
            try:
                with open(prefs_path, 'r') as f:
                    existing_prefs = json.load(f)
            except:
                pass
        
        preferences = {
            "last_stages": stages,
            "last_flags": flags,
            "window_position": window_position if window_position else existing_prefs.get("window_position", {"x": 100, "y": 100})
        }
        
        try:
            with open(prefs_path, 'w') as f:
                json.dump(preferences, f, indent=2)
        except Exception as e:
            # Silently fail if can't save preferences
            pass
    
    def save_window_position(self, x: int, y: int):
        """
        Save window position without affecting stages/flags
        
        Args:
            x: Window x coordinate
            y: Window y coordinate
        """
        prefs_path = Path(self.config_path).parent.parent / self.PREFERENCES_FILE
        
        # Load existing preferences
        preferences = self.load_preferences()
        preferences["window_position"] = {"x": x, "y": y}
        
        try:
            with open(prefs_path, 'w') as f:
                json.dump(preferences, f, indent=2)
        except Exception as e:
            # Silently fail if can't save preferences
            pass
    
    def load_preferences(self) -> Dict:
        """
        Load saved UI preferences
        
        Returns:
            Dict with 'last_stages' and 'last_flags', or defaults if no prefs exist
        """
        prefs_path = Path(self.config_path).parent.parent / self.PREFERENCES_FILE
        
        if not prefs_path.exists():
            # Return defaults
            return {
                "last_stages": self.get_enabled_stages(),
                "last_flags": {flag: info["default"] for flag, info in self.AVAILABLE_FLAGS.items()}
            }
        
        try:
            with open(prefs_path, 'r') as f:
                return json.load(f)
        except Exception:
            # If can't load, return defaults
            return {
                "last_stages": self.get_enabled_stages(),
                "last_flags": {flag: info["default"] for flag, info in self.AVAILABLE_FLAGS.items()}
            }