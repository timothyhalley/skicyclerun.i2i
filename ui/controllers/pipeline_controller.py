"""
Pipeline Controller
Handles subprocess execution of pipeline.py with real-time output streaming
"""
import subprocess
import threading
import os
from typing import Callable, Optional, List, Dict
from pathlib import Path


class PipelineController:
    """Controller for executing pipeline.py as subprocess"""
    
    def __init__(self, workspace_dir: Optional[str] = None):
        """
        Initialize controller
        
        Args:
            workspace_dir: Working directory for pipeline execution (default: current dir)
        """
        self.workspace_dir = Path(workspace_dir) if workspace_dir else Path.cwd()
        self.process: Optional[subprocess.Popen] = None
        self.is_running = False
        self._output_callback: Optional[Callable[[str], None]] = None
        self._completion_callback: Optional[Callable[[int], None]] = None
        self._env_vars: Dict[str, str] = {}
        self._load_environment()
        
    def set_output_callback(self, callback: Callable[[str], None]):
        """
        Set callback for receiving output lines
        
        Args:
            callback: Function that receives each output line as string
        """
        self._output_callback = callback
        
    def set_completion_callback(self, callback: Callable[[int], None]):
        """
        Set callback for process completion
        
        Args:
            callback: Function that receives exit code
        """
        self._completion_callback = callback
    
    def get_environment(self) -> Dict[str, str]:
        """
        Get the environment variables that will be used for pipeline execution
        
        Returns:
            Dictionary of environment variables
        """
        return self._env_vars.copy()
    
    def _load_environment(self):
        """Load required environment variables from current environment or detect paths"""
        # Try to inherit from current environment
        self._env_vars = os.environ.copy()
        
        # Set flag to indicate we're running from UI (disables animated spinners)
        self._env_vars['SKICYCLERUN_UI_MODE'] = '1'
        
        # Check if required variables are already set
        if 'SKICYCLERUN_LIB_ROOT' in self._env_vars and ('HF_HOME' in self._env_vars or 'HUGGINGFACE_CACHE_LIB' in self._env_vars):
            return  # Already configured
        
        # Try to detect common paths
        home = Path.home()
        
        # Look for common image library locations
        potential_roots = [
            Path("/Volumes/MySSD/skicyclerun.i2i"),
            home / "Documents" / "skicyclerun.i2i",
            home / "skicyclerun.i2i",
            self.workspace_dir.parent / "pipeline",
        ]
        
        for root in potential_roots:
            if root.exists():
                self._env_vars['SKICYCLERUN_LIB_ROOT'] = str(root)
                
                # Set HF cache to parent/models
                hf_cache = root.parent / "models"
                hf_cache.mkdir(parents=True, exist_ok=True)
                self._env_vars['HUGGINGFACE_CACHE_LIB'] = str(hf_cache)
                self._env_vars['HF_HOME'] = str(hf_cache)
                self._env_vars['HUGGINGFACE_CACHE'] = str(hf_cache)
                self._env_vars['SKICYCLERUN_MODEL_LIB'] = str(hf_cache)
                
                datasets_cache = hf_cache / "datasets"
                datasets_cache.mkdir(parents=True, exist_ok=True)
                self._env_vars['HF_DATASETS_CACHE'] = str(datasets_cache)
                break
    
    def run_pipeline(self, command_args: List[str]):
        """
        Execute pipeline with given command arguments
        
        Args:
            command_args: Full command including 'python3 pipeline.py' and all arguments
        """
        if self.is_running:
            if self._output_callback:
                self._output_callback("⚠️  Pipeline is already running!\n")
            return
        
        self.is_running = True
        
        # Start subprocess in background thread
        thread = threading.Thread(target=self._run_subprocess, args=(command_args,))
        thread.daemon = True
        thread.start()
    
    def _run_subprocess(self, command_args: List[str]):
        """Internal method to run subprocess with output streaming"""
        try:
            if self._output_callback:
                self._output_callback(f"🚀 Starting pipeline...\n")
                self._output_callback(f"💻 Command: {' '.join(command_args)}\n")
                
                # Show environment status
                if 'SKICYCLERUN_LIB_ROOT' in self._env_vars:
                    self._output_callback(f"📁 Images Root: {self._env_vars['SKICYCLERUN_LIB_ROOT']}\n")
                if 'HF_HOME' in self._env_vars:
                    self._output_callback(f"🤗 HF Cache: {self._env_vars['HF_HOME']}\n")
                
                self._output_callback("="*80 + "\n\n")
            
            # Create subprocess with live output and environment variables
            # Wrap with caffeinate to prevent system sleep during processing
            # stdin=None allows interactive input if --yes flag is not set
            caffeinated_command = ['caffeinate', '-d'] + command_args
            
            self.process = subprocess.Popen(
                caffeinated_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=None,  # Allow interactive prompts (though --yes is default)
                text=True,
                bufsize=1,
                cwd=str(self.workspace_dir),
                env=self._env_vars  # Pass environment variables
            )
            
            # Stream output line by line
            if self.process.stdout:
                for line in iter(self.process.stdout.readline, ''):
                    if line and self._output_callback:
                        self._output_callback(line)
            
            # Wait for completion
            exit_code = self.process.wait()
            
            # Notify completion
            if self._output_callback:
                self._output_callback("\n" + "="*80 + "\n")
                if exit_code == 0:
                    self._output_callback("✅ Pipeline completed successfully!\n")
                else:
                    self._output_callback(f"❌ Pipeline failed with exit code {exit_code}\n")
            
            if self._completion_callback:
                self._completion_callback(exit_code)
                
        except Exception as e:
            if self._output_callback:
                self._output_callback(f"\n❌ Error running pipeline: {e}\n")
            if self._completion_callback:
                self._completion_callback(-1)
        finally:
            self.is_running = False
            self.process = None
    
    def stop_pipeline(self):
        """Stop currently running pipeline process"""
        if self.process and self.is_running:
            if self._output_callback:
                self._output_callback("\n🛑 Stopping pipeline...\n")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.is_running = False
            if self._output_callback:
                self._output_callback("⏹️  Pipeline stopped\n")
