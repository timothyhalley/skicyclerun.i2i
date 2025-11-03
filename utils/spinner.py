import sys, time, threading

class Spinner:
    def __init__(self, message="Processing..."):
        self.message = message
        self.running = False
        self.thread = threading.Thread(target=self.spin)

    def spin(self):
        while self.running:
            for cursor in "|/-\\":
                sys.stdout.write(f"\r🌀 {self.message} {cursor}")
                sys.stdout.flush()
                time.sleep(0.1)

    def start(self):
        self.running = True
        self.thread.start()

    def stop(self):
        self.running = False
        self.thread.join()
        sys.stdout.write("\r✅ Done!\n")