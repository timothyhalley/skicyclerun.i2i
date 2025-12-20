#!/usr/bin/env python3
"""
SkiCycleRun Pipeline UI
Main entry point for native macOS UI application

Usage:
    python3 main.py                    # Launch UI with default config
    python3 main.py --config <path>    # Launch UI with custom config
"""
import sys
import argparse
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent))

from ui import main as run_ui


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="SkiCycleRun Pipeline Runner - Native macOS UI"
    )
    parser.add_argument(
        "--config",
        default="config/pipeline_config.json",
        help="Path to pipeline configuration file (default: config/pipeline_config.json)"
    )
    
    args = parser.parse_args()
    
    # Verify config file exists
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"❌ Error: Config file not found: {config_path}")
        print(f"   Current directory: {Path.cwd()}")
        sys.exit(1)
    
    print("🚀 Launching SkiCycleRun Pipeline UI...")
    print(f"📋 Using config: {config_path}")
    print()
    
    # Launch UI
    run_ui(str(config_path))
