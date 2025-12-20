"""
Main Application
Initializes PyObjC application and coordinates between UI, controller, and model
"""
from Cocoa import NSApplication, NSApp
from ui.models import PipelineConfig
from ui.controllers import PipelineController
from ui.views import MainWindow


class PipelineApp:
    """Main application coordinating UI, controller, and model"""
    
    def __init__(self, config_path: str = "config/pipeline_config.json"):
        """
        Initialize application
        
        Args:
            config_path: Path to pipeline configuration JSON
        """
        # Initialize components
        self.config = PipelineConfig(config_path)
        self.controller = PipelineController()
        
        # Set up controller callbacks
        self.controller.set_output_callback(self._on_output)
        self.controller.set_completion_callback(self._on_complete)
        
        # Create window (PyObjC style)
        self.window = MainWindow.alloc().initWithConfig_(self.config)
        self.window.controller = self.controller  # Pass controller for validation
        self.window.set_run_callback(self._on_run)
        self.window.set_stop_callback(self._on_stop)
    
    def _on_output(self, line: str):
        """Handle output from pipeline controller"""
        # Update UI on main thread
        self.window.append_output(line)
    
    def _on_complete(self, exit_code: int):
        """Handle pipeline completion"""
        self.window.on_pipeline_complete(exit_code)
    
    def _on_run(self, command_args: list):
        """Handle run button click"""
        self.controller.run_pipeline(command_args)
    
    def _on_stop(self):
        """Handle stop button click"""
        self.controller.stop_pipeline()
    
    def run(self):
        """Start the application"""
        # Initialize Cocoa application
        app = NSApplication.sharedApplication()
        
        # Activate app (makes it show in Cmd+Tab and brings to front)
        from Cocoa import NSApplicationActivationPolicyRegular
        app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        
        # Show window
        self.window.show()
        
        # Activate and bring to front
        app.activateIgnoringOtherApps_(True)
        
        # Run event loop
        app.run()


def main(config_path: str = "config/pipeline_config.json"):
    """
    Main entry point for UI application
    
    Args:
        config_path: Path to pipeline configuration
    """
    app = PipelineApp(config_path)
    app.run()


if __name__ == "__main__":
    main()
