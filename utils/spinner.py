import sys, time, threading, os

class Spinner:
    """
    Simple progress indicator for long-running operations.
    Auto-detects UI mode and disables output to prevent UI spam.
    In terminal mode: prints start/end with heartbeat.
    In UI mode: silent (UI has its own progress indicators).
    """
    def __init__(self, message="Processing..."):
        self.message = message
        self.running = False
        self.start_time = None
        self.thread = None
        # Detect if running from UI (PyObjC app sets SKICYCLERUN_UI_MODE)
        self.ui_mode = os.environ.get('SKICYCLERUN_UI_MODE') == '1'

    def spin(self):
        """Background thread that prints periodic heartbeats (every 30 seconds)"""
        while self.running:
            time.sleep(30)
            if self.running:  # Check again after sleep
                elapsed = time.time() - self.start_time
                sys.stdout.write(f"   ⏱️  Still processing... ({int(elapsed)}s elapsed)\n")
                sys.stdout.flush()

    def start(self):
        """Print start message and begin background heartbeat (simplified in UI mode)"""
        self.running = True
        self.start_time = time.time()
        
        # Always print start message (even in UI mode)
        sys.stdout.write(f"🌀 {self.message}...\n")
        sys.stdout.flush()
        
        # Only start heartbeat thread in terminal mode (not UI)
        if not self.ui_mode:
            self.thread = threading.Thread(target=self.spin, daemon=True)
            self.thread.start()

    def stop(self):
        """Print completion message with total elapsed time"""
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=0.5)
        
        elapsed = time.time() - self.start_time if self.start_time else 0
        
        # Always print completion (even in UI mode)
        sys.stdout.write(f"✅ Complete! ({elapsed:.1f}s)\n")
        sys.stdout.flush()