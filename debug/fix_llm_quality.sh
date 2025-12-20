#!/bin/bash
# Quick model comparison test for LLM watermark generation

IMAGE="/Volumes/MySSD/skicyclerun.i2i/pipeline/albums/2025-12-TEST/IMG_3007.jpeg"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🧪 TESTING MODEL QUALITY FOR POI CONTEXT INCORPORATION"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo
echo "ISSUE: llava:7b returns generic output like:"
echo "  'The image features a large clock inside a building,'"
echo "  'possibly a shopping mall or a station.'"
echo
echo "PROBLEM: Model ignores POI context data:"
echo "  • The Big Clock (attraction) - famous hourly performance"
echo "  • Coop's Shot Tower (historic) - built 1889, heritage site"
echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "SOLUTION: Switch to better vision model"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo
echo "✅ Updated config/pipeline_config.json:"
echo "   llm_image_analysis.model: llava:7b → qwen3-vl:32b"
echo
echo "WHY qwen3-vl:32b is better:"
echo "  ✓ Larger model (32B vs 7B parameters)"
echo "  ✓ Better instruction following"
echo "  ✓ Better at incorporating external context"
echo "  ✓ More sophisticated vision understanding"
echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "TEST COMMANDS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo
echo "1️⃣  Test with simplified prompt (faster):"
echo "   python debug/test_ollama_prompt.py \\"
echo "     \"$IMAGE\" \\"
echo "     debug/llm_prompt_simple.txt"
echo
echo "2️⃣  Test with full prompt (comprehensive):"
echo "   python debug/test_ollama_prompt.py \\"
echo "     \"$IMAGE\" \\"
echo "     debug/llm_prompt.txt"
echo
echo "3️⃣  Compare POI sources (AWS vs Overpass):"
echo "   debug/compare_poi_sources.sh --lat -37.81037 --lon 144.96311"
echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "EXPECTED IMPROVEMENT"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo
echo "With qwen3-vl:32b, you should get descriptions like:"
echo "  'In the heart of Melbourne's bustling Central complex,"
echo "   the Big Clock hangs prominently as a modern attraction"
echo "   that draws visitors with its whimsical hourly performance."
echo "   Designed in the style of a giant fob watch...'"
echo
echo "Instead of generic:"
echo "  'The image features a large clock inside a building'"
echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
