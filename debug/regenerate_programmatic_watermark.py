#!/usr/bin/env python3
"""
Regenerate programmatic_watermark for existing master.json entries
WITHOUT re-running the full LLM analysis stage
"""
import sys
import json
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.master_store import MasterStore
from config.pipeline_loader import PipelineLoader

def build_programmatic_watermark(metadata: dict, llm_analysis: dict, config: dict) -> str:
    """
    Build programmatic watermark following format:
    {landmark} {city or region} {state/province if Canada, otherwise country} {emoji} SkiCyclerun {copyright} {year}
    
    Example: Knox Mountain Kelowna BC 🎿 SkiCyclerun © 2024
    """
    location = metadata.get('location', {})
    country = location.get('country', 'Unknown')
    city = location.get('city', 'Unknown')
    state = location.get('state', '')
    
    # Get landmark from closest POI or landmark_clues
    landmark = ""
    closest_poi = llm_analysis.get('closest_poi')
    if closest_poi:
        landmark = closest_poi.get('name', '')
    
    # Fallback to landmark_clues if no POI
    if not landmark:
        landmark_clues = llm_analysis.get('landmark_clues', '')
        if landmark_clues and landmark_clues.lower() not in ['none', 'n/a', 'no landmarks visible', 'no landmarks']:
            # Extract first landmark if multiple
            if isinstance(landmark_clues, str) and ',' in landmark_clues:
                landmark = landmark_clues.split(',')[0].strip()
            else:
                landmark = str(landmark_clues).strip()
    
    # Build location part: city/region + state/country
    if country == 'Canada' and state:
        # Canada: include province (BC, ON, etc.)
        location_part = f"{city} {state}"
    elif country == 'United States' and state:
        # US: include state
        location_part = f"{city} {state}"
    else:
        # Other countries: just city and country
        location_part = f"{city} {country}"
    
    # Get emoji and copyright from config (with defaults)
    watermark_config = config.get('watermark', {})
    symbol = watermark_config.get('symbol', '🎿')
    fixed_year = watermark_config.get('fixed_year')
    year = fixed_year if fixed_year else datetime.now().year + watermark_config.get('year_offset', 1)
    
    # Build watermark
    parts = []
    if landmark:
        parts.append(landmark)
    parts.append(location_part)
    parts.append(symbol)
    parts.append("SkiCyclerun")
    parts.append(f"© {year}")
    
    return " ".join(parts)

def main():
    print("\n" + "="*80)
    print("  REGENERATING PROGRAMMATIC WATERMARKS")
    print("="*80 + "\n")
    
    # Load config
    loader = PipelineLoader()
    config = loader.load()
    
    # Load master store
    master_store = MasterStore(config['paths']['master_catalog'])
    
    updated = 0
    skipped = 0
    
    for path_str, entry in master_store.list_paths().items():
        llm_analysis = entry.get('llm_image_analysis', {})
        
        # Skip if no LLM analysis
        if not llm_analysis:
            skipped += 1
            continue
        
        # Skip if programmatic_watermark already exists
        if llm_analysis.get('programmatic_watermark'):
            skipped += 1
            continue
        
        # Generate programmatic watermark
        try:
            programmatic_watermark = build_programmatic_watermark(entry, llm_analysis, config)
            
            # Update entry
            patch = {
                'llm_image_analysis': {
                    **llm_analysis,
                    'programmatic_watermark': programmatic_watermark
                }
            }
            
            master_store.update_entry(path_str, patch, stage='llm_image_analysis')
            
            print(f"✓ {Path(path_str).name}")
            print(f"  Watermark: {programmatic_watermark}\n")
            
            updated += 1
            
        except Exception as e:
            print(f"✗ {Path(path_str).name}: {e}\n")
            skipped += 1
    
    print("="*80)
    print(f"✅ Complete!")
    print(f"   Updated: {updated}")
    print(f"   Skipped: {skipped}")
    print("="*80 + "\n")

if __name__ == '__main__':
    main()
