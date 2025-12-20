#!/usr/bin/env python3
"""
Test programmatic watermark generation
Verifies format: {landmark} {city/region} {state/province if Canada, else country} {emoji} SkiCyclerun © {year}
"""
import sys
from pathlib import Path
import json

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.ollama_watermark_analyzer import OllamaWatermarkAnalyzer

def test_programmatic_watermark():
    """Test various location scenarios"""
    
    # Load config
    config_path = Path(__file__).parent.parent / "config" / "pipeline_config.json"
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    analyzer = OllamaWatermarkAnalyzer(config)
    
    # Test cases
    test_cases = [
        {
            "name": "Canadian location with landmark",
            "metadata": {
                "location": {
                    "city": "Kelowna",
                    "state": "BC",
                    "country": "Canada",
                }
            },
            "primary_subject": {
                "closest_poi": {"name": "Knox Mountain"}
            },
            "expected": "Knox Mountain Kelowna BC"
        },
        {
            "name": "US location with landmark",
            "metadata": {
                "location": {
                    "city": "Vail",
                    "state": "Colorado",
                    "country": "United States",
                }
            },
            "primary_subject": {
                "closest_poi": {"name": "Vail Mountain"}
            },
            "expected": "Vail Mountain Vail Colorado"
        },
        {
            "name": "International location with landmark",
            "metadata": {
                "location": {
                    "city": "Chamonix",
                    "state": "",
                    "country": "France",
                }
            },
            "primary_subject": {
                "closest_poi": {"name": "Mont Blanc"}
            },
            "expected": "Mont Blanc Chamonix France"
        },
        {
            "name": "Location without POI (uses landmark_clues)",
            "metadata": {
                "location": {
                    "city": "Whistler",
                    "state": "BC",
                    "country": "Canada",
                }
            },
            "primary_subject": {
                "closest_poi": None,
                "landmark_clues": "Whistler Blackcomb, Peak 2 Peak Gondola"
            },
            "expected": "Whistler Blackcomb Whistler BC"
        }
    ]
    
    print("Testing Programmatic Watermark Generation")
    print("=" * 80)
    
    for test in test_cases:
        print(f"\n{test['name']}:")
        result = analyzer.build_programmatic_watermark(
            test["metadata"],
            test["primary_subject"]
        )
        print(f"  Result:   {result}")
        print(f"  Expected: {test['expected']} [emoji] SkiCyclerun © [year]")
        
        # Check if result starts with expected prefix
        if result.startswith(test['expected']):
            print("  ✅ PASS")
        else:
            print(f"  ❌ FAIL - Expected to start with '{test['expected']}'")
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    test_programmatic_watermark()
