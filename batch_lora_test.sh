#!/bin/zsh

# Batch LoRA Testing Script
# Run multiple LoRA styles against the same batch of images

# Usage: ./batch_lora_test.sh [input_folder]
# Example: ./batch_lora_test.sh input/test_images

set -e  # Exit on error

# Default input folder if not provided
INPUT_FOLDER="${1:-input}"

# Check if input folder exists
if [ ! -d "$INPUT_FOLDER" ]; then
    echo "❌ Error: Input folder '$INPUT_FOLDER' does not exist"
    echo "Usage: $0 [input_folder]"
    exit 1
fi

# Array of LoRAs to test
LORAS=(
    "Ghibli"
    "Jojo"
    "Irasutoya"
    "LEGO"
    "Pixel"
    "Rick_Morty"
    "Snoopy"
    "American_Cartoon"
    "3D_Chibi"
    "Clay_Toy"
)

echo "🚀 Starting batch LoRA testing"
echo "📁 Input folder: $INPUT_FOLDER"
echo "🎨 Testing ${#LORAS[@]} LoRA styles"
echo ""

START_TIME=$(date +%s)

# Iterate through each LoRA
for LORA in "${LORAS[@]}"; do
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "🎨 Processing with LoRA: $LORA"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    LORA_START=$(date +%s)
    
    # Run the batch processing
    python main.py --lora "$LORA" --file "$INPUT_FOLDER" --batch
    
    LORA_END=$(date +%s)
    LORA_DURATION=$((LORA_END - LORA_START))
    
    echo "✅ Completed $LORA in ${LORA_DURATION}s"
    echo ""
done

END_TIME=$(date +%s)
TOTAL_DURATION=$((END_TIME - START_TIME))

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎉 All LoRA tests completed!"
echo "⏱️  Total time: ${TOTAL_DURATION}s"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
