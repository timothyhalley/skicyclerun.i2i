#!/usr/bin/env python3
import json
from pathlib import Path

config_path = Path("config/pipeline_config.json")
with open(config_path) as f:
    config = json.load(f)

font_config = config['watermark']['font']

output = f"""
CONFIG FILE CHECK
=================
Config path: {config_path.absolute()}
Font size: {font_config['size']}
Font family: {font_config['family']}
Font color: {font_config['color']}
Stroke width: {font_config['stroke_width']}
Margin: {config['watermark']['margin']}
"""

print(output)

# Also write to file
with open("debug_output.txt", "w") as f:
    f.write(output)

print("\n✅ Written to debug_output.txt")
