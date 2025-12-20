"""
Main Window View
Native macOS window using PyObjC with stage checkboxes, flags, and run controls
"""
import objc
from Cocoa import (
    NSObject, NSWindow, NSView, NSButton, NSTextField, NSScrollView, NSTextView,
    NSMakeRect, NSMakeSize, NSMakePoint, NSFont, NSColor,
    NSBezelBorder, NSButtonTypeSwitch, NSButtonTypeMomentaryPushIn,
    NSWindowStyleMaskTitled, NSWindowStyleMaskClosable, NSWindowStyleMaskResizable,
    NSBackingStoreBuffered, NSTextFieldSquareBezel
)
from typing import Callable, List, Dict, Optional
from ui.models import PipelineConfig


class MainWindow(NSObject):
    """Main application window with pipeline controls"""
    
    @classmethod
    def alloc(cls):
        """Override alloc to return proper instance"""
        return cls.allocWithZone_(None)
    
    def initWithConfig_(self, pipeline_config: PipelineConfig):
        """
        Initialize main window (Objective-C style initializer)
        
        Args:
            pipeline_config: Pipeline configuration model
        """
        # Initialize NSObject superclass
        self = objc.super(MainWindow, self).init()
        if self is None:
            return None
            
        self.config = pipeline_config
        self.controller = None  # Will be set by app.py
        self.window = None
        self.stage_checkboxes: Dict[str, NSButton] = {}
        self.flag_checkboxes: Dict[str, NSButton] = {}
        self.command_preview_field = None
        self.output_text_view = None
        self.run_button = None
        self.stop_button = None
        
        # Callbacks
        self._run_callback: Optional[Callable[[List[str]], None]] = None
        self._stop_callback: Optional[Callable[[], None]] = None
        
        self._create_window()
        self._create_ui_elements()
        
        return self
    
    def _create_window(self):
        """Create main window"""
        # Load saved window position or use defaults
        prefs = self.config.load_preferences()
        window_pos = prefs.get("window_position", {"x": 100, "y": 100})
        x = window_pos.get("x", 100)
        y = window_pos.get("y", 100)
        
        # Create window (x, y, width, height)
        rect = NSMakeRect(x, y, 900, 750)
        
        # Import NSWindowStyleMaskMiniaturizable from Cocoa
        from Cocoa import NSWindowStyleMaskMiniaturizable
        
        style_mask = (NSWindowStyleMaskTitled | 
                     NSWindowStyleMaskClosable | 
                     NSWindowStyleMaskMiniaturizable |
                     NSWindowStyleMaskResizable)
        
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, style_mask, NSBackingStoreBuffered, False
        )
        self.window.setTitle_("SkiCycleRun Pipeline Runner")
        self.window.setDelegate_(self)
        
        # Set minimum size
        self.window.setMinSize_(NSMakeSize(700, 600))
        
        # Enable full screen button (green dot maximize)
        from Cocoa import NSWindowCollectionBehaviorFullScreenPrimary, NSAppearance
        self.window.setCollectionBehavior_(NSWindowCollectionBehaviorFullScreenPrimary)
        
        # Use system appearance (dark mode / light mode)
        self.window.setAppearance_(None)  # None = inherit from system
    
    def _create_ui_elements(self):
        """Create tabbed UI with proper autoresizing"""
        from Cocoa import (NSViewWidthSizable, NSViewHeightSizable, NSViewMaxYMargin,
                           NSTabView, NSTabViewItem, NSView)
        
        content_view = self.window.contentView()
        frame = content_view.frame()
        window_width = frame.size.width
        window_height = frame.size.height
        
        # Title at top
        title_height = 40
        title = NSTextField.alloc().initWithFrame_(NSMakeRect(20, window_height - title_height, window_width - 40, 30))
        title.setStringValue_("🏔️ SkiCycleRun Photo Processing Pipeline")
        title.setEditable_(False)
        title.setBordered_(False)
        title.setBackgroundColor_(NSColor.clearColor())
        title.setFont_(NSFont.boldSystemFontOfSize_(18))
        title.setAutoresizingMask_(NSViewWidthSizable | NSViewMaxYMargin)
        content_view.addSubview_(title)
        
        # Tab view (fills rest of window)
        tab_view = NSTabView.alloc().initWithFrame_(NSMakeRect(10, 10, window_width - 20, window_height - title_height - 20))
        tab_view.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        content_view.addSubview_(tab_view)
        
        # Create Input tab
        input_tab = NSTabViewItem.alloc().initWithIdentifier_("input")
        input_tab.setLabel_("⚙️ Configuration")
        input_view = NSView.alloc().initWithFrame_(tab_view.contentRect())
        input_tab.setView_(input_view)
        tab_view.addTabViewItem_(input_tab)
        
        # Create Output tab
        output_tab = NSTabViewItem.alloc().initWithIdentifier_("output")
        output_tab.setLabel_("📟 Console Output")
        output_view = NSView.alloc().initWithFrame_(tab_view.contentRect())
        output_tab.setView_(output_view)
        tab_view.addTabViewItem_(output_tab)
        
        self.tab_view = tab_view
        self._create_input_tab(input_view)
        self._create_output_tab(output_view)
    
    def _create_input_tab(self, parent_view):
        """Create configuration controls in input tab"""
        from Cocoa import NSViewWidthSizable, NSViewMaxYMargin
        
        frame = parent_view.frame()
        width = frame.size.width
        height = frame.size.height
        y_pos = height - 20
        
        # Load saved preferences
        prefs = self.config.load_preferences()
        saved_stages = prefs.get("last_stages", self.config.get_enabled_stages())
        saved_flags = prefs.get("last_flags", {flag: info["default"] for flag, info in self.config.AVAILABLE_FLAGS.items()})
        
        # Stages section
        stages_label = self._create_label("Pipeline Stages:", 20, y_pos, width - 40, 20)
        stages_label.setAutoresizingMask_(NSViewWidthSizable | NSViewMaxYMargin)
        parent_view.addSubview_(stages_label)
        y_pos -= 30
        
        # Create stage checkboxes in 2 columns
        col1_x, col2_x = 30, max(450, width // 2 + 20)
        col_y = y_pos
        
        for i, stage in enumerate(self.config.AVAILABLE_STAGES):
            x_pos = col1_x if i < 4 else col2_x
            if i == 4:
                col_y = y_pos  # Reset y for second column
            
            checkbox = NSButton.alloc().initWithFrame_(NSMakeRect(x_pos, col_y, 400, 20))
            checkbox.setButtonType_(NSButtonTypeSwitch)
            
            # Format stage name with description
            desc = self.config.STAGE_DESCRIPTIONS.get(stage, "")
            checkbox.setTitle_(f"{stage}  —  {desc}")
            
            # Check if enabled in saved preferences
            checkbox.setState_(1 if stage in saved_stages else 0)
            checkbox.setTarget_(self)
            checkbox.setAction_("updateCommandPreview:")
            checkbox.setAutoresizingMask_(NSViewMaxYMargin)
            
            parent_view.addSubview_(checkbox)
            self.stage_checkboxes[stage] = checkbox
            col_y -= 25
        
        y_pos -= 140
        
        # Flags section
        flags_label = self._create_label("Command Flags:", 20, y_pos, width - 40, 20)
        flags_label.setAutoresizingMask_(NSViewWidthSizable | NSViewMaxYMargin)
        parent_view.addSubview_(flags_label)
        y_pos -= 30
        
        # Create flag checkboxes in 2 columns
        col_y = y_pos
        flag_items = list(self.config.AVAILABLE_FLAGS.items())
        
        for i, (flag_name, flag_info) in enumerate(flag_items):
            x_pos = col1_x if i < 4 else col2_x
            if i == 4:
                col_y = y_pos
            
            checkbox = NSButton.alloc().initWithFrame_(NSMakeRect(x_pos, col_y, 400, 20))
            checkbox.setButtonType_(NSButtonTypeSwitch)
            checkbox.setTitle_(f"--{flag_name.replace('_', '-')}  —  {flag_info['description']}")
            # Use saved preference if available, otherwise default
            checkbox.setState_(1 if saved_flags.get(flag_name, flag_info['default']) else 0)
            checkbox.setTarget_(self)
            checkbox.setAction_("updateCommandPreview:")
            checkbox.setAutoresizingMask_(NSViewMaxYMargin)
            
            # Special handling for --yes flag: keep it checked and disabled in GUI mode
            if flag_name == "yes":
                checkbox.setState_(1)  # Always checked
                checkbox.setEnabled_(False)  # Grayed out/disabled
                checkbox.setTitle_(f"--{flag_name.replace('_', '-')}  —  Required (GUI can't handle interactive prompts)")
            
            parent_view.addSubview_(checkbox)
            self.flag_checkboxes[flag_name] = checkbox
            col_y -= 25
        
        y_pos -= 120
        
        # Command preview at bottom
        preview_label = self._create_label("Command Preview:", 20, 90, width - 40, 20)
        preview_label.setAutoresizingMask_(NSViewWidthSizable)
        parent_view.addSubview_(preview_label)
        
        self.command_preview_field = NSTextField.alloc().initWithFrame_(NSMakeRect(20, 40, width - 40, 40))
        self.command_preview_field.setEditable_(False)
        self.command_preview_field.setSelectable_(True)  # Allow text selection for copying
        self.command_preview_field.setBezeled_(True)
        self.command_preview_field.setBezelStyle_(NSTextFieldSquareBezel)
        self.command_preview_field.setFont_(NSFont.fontWithName_size_("Monaco", 10))
        self.command_preview_field.setAutoresizingMask_(NSViewWidthSizable)
        parent_view.addSubview_(self.command_preview_field)
        
        # Run/Stop buttons at bottom
        self.run_button = NSButton.alloc().initWithFrame_(NSMakeRect(20, 5, 150, 28))
        self.run_button.setTitle_("▶️ Run Pipeline")
        self.run_button.setButtonType_(NSButtonTypeMomentaryPushIn)
        self.run_button.setBezelStyle_(4)
        self.run_button.setTarget_(self)
        self.run_button.setAction_("runPipeline:")
        parent_view.addSubview_(self.run_button)
        
        self.stop_button = NSButton.alloc().initWithFrame_(NSMakeRect(180, 5, 150, 28))
        self.stop_button.setTitle_("⏹️ Stop")
        self.stop_button.setButtonType_(NSButtonTypeMomentaryPushIn)
        self.stop_button.setBezelStyle_(4)
        self.stop_button.setTarget_(self)
        self.stop_button.setAction_("stopPipeline:")
        self.stop_button.setEnabled_(False)
        parent_view.addSubview_(self.stop_button)
        
        # Environment info at bottom
        env_info = NSTextField.alloc().initWithFrame_(NSMakeRect(340, 8, width - 360, 22))
        env_info.setStringValue_("💡 Tip: Environment variables auto-detected. Run 'source ./env_setup.sh <path>' in terminal if needed.")
        env_info.setEditable_(False)
        env_info.setBordered_(False)
        env_info.setBackgroundColor_(NSColor.clearColor())
        env_info.setFont_(NSFont.systemFontOfSize_(10))
        env_info.setAutoresizingMask_(NSViewWidthSizable)
        parent_view.addSubview_(env_info)
    
    def _create_output_tab(self, parent_view):
        """Create console output in output tab"""
        from Cocoa import (NSViewWidthSizable, NSViewHeightSizable, NSViewMaxYMargin,
                           NSProgressIndicator, NSProgressIndicatorStyleBar)
        
        frame = parent_view.frame()
        width = frame.size.width
        height = frame.size.height
        
        # Progress bar at top
        progress_y = height - 35
        self.progress_indicator = NSProgressIndicator.alloc().initWithFrame_(
            NSMakeRect(10, progress_y, width - 20, 20)
        )
        self.progress_indicator.setStyle_(NSProgressIndicatorStyleBar)
        self.progress_indicator.setIndeterminate_(False)
        self.progress_indicator.setMinValue_(0.0)
        self.progress_indicator.setMaxValue_(100.0)
        self.progress_indicator.setDoubleValue_(0.0)
        self.progress_indicator.setHidden_(True)  # Hide initially
        self.progress_indicator.setAutoresizingMask_(NSViewWidthSizable | NSViewMaxYMargin)
        parent_view.addSubview_(self.progress_indicator)
        
        # Progress label (shows current stage)
        self.progress_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(10, progress_y - 25, width - 20, 20)
        )
        self.progress_label.setStringValue_("")
        self.progress_label.setEditable_(False)
        self.progress_label.setBordered_(False)
        self.progress_label.setBackgroundColor_(NSColor.clearColor())
        self.progress_label.setFont_(NSFont.systemFontOfSize_(12))
        self.progress_label.setHidden_(True)  # Hide initially
        self.progress_label.setAutoresizingMask_(NSViewWidthSizable | NSViewMaxYMargin)
        parent_view.addSubview_(self.progress_label)
        
        # Scrollable output (below progress bar)
        scroll_view = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(10, 10, width - 20, height - 60)
        )
        scroll_view.setHasVerticalScroller_(True)
        scroll_view.setBorderType_(NSBezelBorder)
        scroll_view.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        
        self.output_text_view = NSTextView.alloc().initWithFrame_(scroll_view.contentView().bounds())
        self.output_text_view.setEditable_(False)
        self.output_text_view.setFont_(NSFont.fontWithName_size_("Monaco", 16))
        self.output_text_view.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        
        # Set theme-aware background color
        self._apply_output_theme()
        
        scroll_view.setDocumentView_(self.output_text_view)
        parent_view.addSubview_(scroll_view)
        self.scroll_view = scroll_view
        
        # Track pipeline state
        self.total_stages = 0
        self.completed_stages = 0
        self.current_stage_name = ""
        
        # Initial command preview update
        self.updateCommandPreview_(None)
    
    def _create_label(self, text: str, x: float, y: float, width: float, height: float) -> NSTextField:
        """Helper to create a label"""
        label = NSTextField.alloc().initWithFrame_(NSMakeRect(x, y, width, height))
        label.setStringValue_(text)
        label.setEditable_(False)
        label.setBordered_(False)
        label.setBackgroundColor_(NSColor.clearColor())
        label.setFont_(NSFont.boldSystemFontOfSize_(13))
        return label
    
    def _apply_output_theme(self):
        """Apply theme-aware colors to output text view"""
        from Cocoa import NSAppearance
        
        # Get effective appearance (light or dark)
        appearance = NSAppearance.currentDrawingAppearance()
        if appearance is None:
            appearance = NSAppearance.appearanceNamed_("NSAppearanceNameAqua")
        
        appearance_name = appearance.name()
        
        # Detect dark mode
        is_dark_mode = "Dark" in appearance_name
        
        if is_dark_mode:
            # Dark mode: keep default dark background
            # NSTextView default dark mode is fine
            pass
        else:
            # Light mode: use slightly dimmed white (not pure white)
            # RGB: 245, 245, 245 (slightly off-white)
            bg_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.96, 0.96, 0.96, 1.0)
            self.output_text_view.setBackgroundColor_(bg_color)
            
            # Also set text color to dark gray for better contrast
            text_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.1, 0.1, 0.1, 1.0)
            self.output_text_view.setTextColor_(text_color)
    
    def updateCommandPreview_(self, sender):
        """Update command preview based on selected stages/flags"""
        stages = self._get_selected_stages()
        flags = self._get_selected_flags()
        
        # Save preferences whenever selections change
        self.config.save_preferences(stages, flags)
        
        command_str = self.config.get_command_string(stages=stages, flags=flags)
        self.command_preview_field.setStringValue_(command_str)
    
    def runPipeline_(self, sender):
        """Run pipeline button clicked"""
        stages = self._get_selected_stages()
        flags = self._get_selected_flags()
        
        # Pre-flight validation
        validation_result = self._validate_before_run(stages, flags)
        
        if validation_result["errors"]:
            # Show error dialog and abort
            self._show_validation_errors(validation_result["errors"])
            return
        
        # Show warnings but continue
        if validation_result["warnings"]:
            # Log warnings to output
            self.output_text_view.setString_("")
            self.tab_view.selectTabViewItemAtIndex_(1)  # Switch to Console Output tab
            for warning in validation_result["warnings"]:
                self.append_output(f"⚠️  WARNING: {warning}\n")
            self.append_output("\n")
        
        command_args = self.config.build_command(stages=stages, flags=flags)
        
        # Disable run button, enable stop button
        self.run_button.setEnabled_(False)
        self.stop_button.setEnabled_(True)
        
        # Clear output and switch to output tab (if not already done)
        if not validation_result["warnings"]:
            self.output_text_view.setString_("")
            self.tab_view.selectTabViewItemAtIndex_(1)
        
        # Trigger callback
        if self._run_callback:
            self._run_callback(command_args)
    
    def stopPipeline_(self, sender):
        """Stop pipeline button clicked"""
        if self._stop_callback:
            self._stop_callback()
    
    def _get_selected_stages(self) -> List[str]:
        """Get list of selected stages"""
        return [stage for stage, checkbox in self.stage_checkboxes.items() 
                if checkbox.state() == 1]
    
    def _get_selected_flags(self) -> Dict[str, bool]:
        """Get dict of selected flags"""
        return {flag: (checkbox.state() == 1) 
                for flag, checkbox in self.flag_checkboxes.items()}
    
    def _validate_before_run(self, stages: List[str], flags: Dict[str, bool]) -> Dict[str, List[str]]:
        """
        Validate configuration before running pipeline
        
        Returns:
            Dict with 'errors' (blocking) and 'warnings' (non-blocking) lists
        """
        from pathlib import Path
        
        errors = []
        warnings = []
        
        # Get environment from controller (includes auto-detected paths)
        env = self.controller.get_environment() if hasattr(self, 'controller') else {}
        
        # Check required environment variables
        if 'SKICYCLERUN_LIB_ROOT' not in env:
            errors.append("SKICYCLERUN_LIB_ROOT environment variable not set")
        
        if 'HF_HOME' not in env and 'HUGGINGFACE_CACHE_LIB' not in env:
            errors.append("HF_HOME or HUGGINGFACE_CACHE_LIB environment variable not set")
        
        # If env vars are set, check paths exist
        if 'SKICYCLERUN_LIB_ROOT' in env:
            lib_root = Path(env['SKICYCLERUN_LIB_ROOT'])
            if not lib_root.exists():
                errors.append(f"Images root directory does not exist: {lib_root}")
            else:
                # Check for images if not running export stage
                if 'export' not in stages:
                    albums_path = lib_root / "pipeline" / "albums"
                    if albums_path.exists():
                        # Check for images recursively
                        image_patterns = ["*.jpg", "*.JPG", "*.jpeg", "*.JPEG", "*.png", "*.PNG"]
                        image_files = []
                        for pattern in image_patterns:
                            image_files.extend(albums_path.rglob(pattern))
                        
                        if len(image_files) == 0:
                            warnings.append("No images found in albums folder. Pipeline may have nothing to process.")
                    else:
                        warnings.append("Albums folder does not exist. Run 'export' stage first or create folder manually.")
        
        if 'HF_HOME' in env:
            hf_cache = Path(env['HF_HOME'])
            if not hf_cache.exists():
                warnings.append(f"HuggingFace cache directory will be created: {hf_cache}")
        
        # Check if any stages are selected
        if not stages:
            errors.append("No stages selected. Please select at least one stage to run.")
        
        # Check for stage-specific requirements
        if 'lora_processing' in stages:
            # Check if LoRA registry exists
            lora_registry = Path("config/lora_registry.json")
            if not lora_registry.exists():
                warnings.append("LoRA registry not found. LoRA processing may fail.")
        
        return {"errors": errors, "warnings": warnings}
    
    def _show_validation_errors(self, errors: List[str]):
        """Show error dialog with validation failures"""
        from Cocoa import NSAlert, NSAlertStyleCritical, NSAlertFirstButtonReturn
        
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Cannot Run Pipeline")
        alert.setInformativeText_("The following errors must be fixed before running:\n\n" + 
                                  "\n".join(f"• {error}" for error in errors))
        alert.setAlertStyle_(NSAlertStyleCritical)
        alert.addButtonWithTitle_("OK")
        alert.runModal()
    
    def append_output(self, text: str):
        """
        Append text to output console
        Thread-safe: Ensures UI updates happen on main thread
        """
        # Parse output for progress tracking
        self._parse_progress(text)
        
        # Schedule UI update on main thread
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "appendOutputOnMainThread:",
            text,
            False
        )
    
    def _parse_progress(self, text: str):
        """Parse pipeline output to track progress"""
        import re
        
        # Detect total stages from initial log
        # Example: "📋 Stages to run: export, cleanup, metadata_extraction"
        stages_match = re.search(r'📋 Stages to run: (.+)', text)
        if stages_match:
            stages_str = stages_match.group(1)
            stages = [s.strip() for s in stages_str.split(',')]
            self.total_stages = len(stages)
            self.completed_stages = 0
            
            # Show progress bar
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "showProgressBar:", None, False
            )
        
        # Detect stage start
        # Example: "▶️  STAGE: METADATA EXTRACTION"
        stage_start_match = re.search(r'▶️\s+STAGE:\s+(.+)', text)
        if stage_start_match:
            stage_name = stage_start_match.group(1).strip()
            self.current_stage_name = stage_name
            self._update_progress()
        
        # Detect long-running operation start (spinner messages)
        # Example: "🌀 Running inference on IMG_1234.jpg..."
        if '🌀' in text and 'Running inference' in text:
            # Switch to indeterminate mode during inference
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "setIndeterminateProgress:", True, False
            )
        
        # Detect operation completion
        if '✅ Complete!' in text:
            # Switch back to determinate mode
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "setIndeterminateProgress:", False, False
            )
        
        # Detect stage completion markers (look for next stage or pipeline complete)
        if '🎉 Pipeline complete!' in text or '✅ Pipeline completed successfully' in text:
            self.completed_stages = self.total_stages
            self._update_progress()
            
            # Hide progress bar after completion
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "hideProgressBar:", None, False
            )
    
    def _update_progress(self):
        """Update progress bar and label"""
        if self.total_stages == 0:
            return
        
        # Calculate progress percentage
        progress = (self.completed_stages / self.total_stages) * 100
        
        # Update on main thread
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "updateProgressBarOnMainThread:",
            {"progress": progress, "stage": self.current_stage_name},
            False
        )
        
        # Increment completed count for next stage
        if self.current_stage_name:
            self.completed_stages += 1
    
    def showProgressBar_(self, sender):
        """Show progress bar and label (main thread)"""
        self.progress_indicator.setHidden_(False)
        self.progress_label.setHidden_(False)
        self.progress_indicator.setDoubleValue_(0.0)
        self.progress_label.setStringValue_("Starting pipeline...")
    
    def hideProgressBar_(self, sender):
        """Hide progress bar and label (main thread)"""
        self.progress_indicator.setHidden_(True)
        self.progress_label.setHidden_(True)
    
    def setIndeterminateProgress_(self, is_indeterminate):
        """Switch between determinate and indeterminate progress (main thread)"""
        if is_indeterminate:
            self.progress_indicator.setIndeterminate_(True)
            self.progress_indicator.startAnimation_(None)
            self.progress_label.setStringValue_(f"Processing: {self.current_stage_name}...")
        else:
            self.progress_indicator.setIndeterminate_(False)
            self.progress_indicator.stopAnimation_(None)
            self._update_progress()  # Update to current determinate value
    
    def updateProgressBarOnMainThread_(self, data: dict):
        """Update progress bar value and label (main thread)"""
        progress = data.get("progress", 0)
        stage = data.get("stage", "")
        
        self.progress_indicator.setDoubleValue_(progress)
        
        if stage:
            self.progress_label.setStringValue_(f"Running: {stage}")
        else:
            self.progress_label.setStringValue_(f"Progress: {progress:.0f}%")
    
    def appendOutputOnMainThread_(self, text: str):
        """Actual UI update - must run on main thread"""
        current = self.output_text_view.string()
        self.output_text_view.setString_(current + text)
        
        # Auto-scroll to bottom
        self.output_text_view.scrollRangeToVisible_((len(current + text), 0))
    
    def on_pipeline_complete(self, exit_code: int):
        """
        Called when pipeline finishes
        Thread-safe: Ensures UI updates happen on main thread
        """
        # Schedule UI update on main thread
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "onPipelineCompleteOnMainThread:",
            exit_code,
            False
        )
    
    def onPipelineCompleteOnMainThread_(self, exit_code: int):
        """Actual UI update - must run on main thread"""
        self.run_button.setEnabled_(True)
        self.stop_button.setEnabled_(False)
        
        # Hide progress bar
        self.progress_indicator.setHidden_(True)
        self.progress_label.setHidden_(True)
        
        # Reset tracking
        self.total_stages = 0
        self.completed_stages = 0
        self.current_stage_name = ""
        
        self.append_output(f"\n\n✅ Pipeline completed with exit code: {exit_code}\n")
    
    def set_run_callback(self, callback: Callable[[List[str]], None]):
        """Set callback for run button"""
        self._run_callback = callback
    
    def set_stop_callback(self, callback: Callable[[], None]):
        """Set callback for stop button"""
        self._stop_callback = callback
    
    def windowShouldClose_(self, sender):
        """
        Called when user clicks red close button
        Stop any running pipeline and terminate the application
        """
        # Save window position before closing
        try:
            frame = self.window.frame()
            self.config.save_window_position(int(frame.origin.x), int(frame.origin.y))
        except Exception as e:
            print(f"Warning: Failed to save window position: {e}")
        
        # Stop pipeline if running
        if self._stop_callback:
            try:
                self._stop_callback()
            except Exception as e:
                print(f"Warning: Failed to stop pipeline: {e}")
        
        # Close window first
        self.window.close()
        
        # Force terminate the application
        import os
        import signal
        from Cocoa import NSApplication
        
        # Try graceful termination first
        NSApplication.sharedApplication().terminate_(None)
        
        # If that didn't work, force quit
        os.kill(os.getpid(), signal.SIGTERM)
        
        return True
    
    def show(self):
        """Show the window"""
        self.window.makeKeyAndOrderFront_(None)
