#!/bin/zsh

# Batch LoRA Testing Script
# Run multiple LoRA styles against the same batch of images or single file

# Usage: ./batch_lora_test.sh [options]
# Options:
#   --file <path>           Process a single image file
#   --input-folder <path>   Process all images in folder (batch mode)
#   --output-folder <path>  Override output folder (optional)
# Examples:
#   ./batch_lora_test.sh --file /path/to/image.webp
#   ./batch_lora_test.sh --input-folder /path/to/images
#   ./batch_lora_test.sh --input-folder /path/to/images --output-folder /path/to/output

set -e  # Exit on error

# Default values
INPUT_FILE=""
INPUT_FOLDER=""
OUTPUT_FOLDER=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --file)
            INPUT_FILE="$2"
            shift 2
            ;;
        --input-folder)
            INPUT_FOLDER="$2"
            shift 2
            ;;
        --output-folder)
            OUTPUT_FOLDER="$2"
            shift 2
            ;;
        *)
            echo "❌ Unknown option: $1"
            echo "Usage: $0 [--file <path>] [--input-folder <path>] [--output-folder <path>]"
            exit 1
            ;;
    esac
done

# Validate input
if [ -z "$INPUT_FILE" ] && [ -z "$INPUT_FOLDER" ]; then
    echo "❌ Error: Must specify either --file or --input-folder"
    echo "Usage: $0 [--file <path>] [--input-folder <path>] [--output-folder <path>]"
    exit 1
fi

if [ -n "$INPUT_FILE" ] && [ -n "$INPUT_FOLDER" ]; then
    echo "❌ Error: Cannot specify both --file and --input-folder"
    exit 1
fi

# Check if input exists
if [ -n "$INPUT_FILE" ] && [ ! -f "$INPUT_FILE" ]; then
    echo "❌ Error: File '$INPUT_FILE' does not exist"
    exit 1
fi

if [ -n "$INPUT_FOLDER" ] && [ ! -d "$INPUT_FOLDER" ]; then
    echo "❌ Error: Folder '$INPUT_FOLDER' does not exist"
    exit 1
fi

# Array of LoRAs to test
LORAS=(
    "Paper_Cutting"
    # "Irasutoya"
    # "Fabric"
    "Chinese_Ink"
    "Origami"
    "Oil_Painting"
    # "Poly"
    # "LEGO"
    "Line"
    # "Snoopy"
    # "Picasso"
    # "American_Cartoon"
    # "Macaron"
    # "Vector"
    # "Van_Gogh"
    # "Clay_Toy"
    "Super_Pencil"
    "Poly_Futurism"
    # "Glass_Prism"
    "Sketch"
    "Ink_Wash"
    "FractalGeometry"  
    "WatercolorFlux"
    "Gorillaz"
    "PencilDrawing"
    "Afremov"
)

echo "🚀 Starting batch LoRA testing"
if [ -n "$INPUT_FILE" ]; then
    echo "📄 Input file: $INPUT_FILE"
    echo "🔀 Mode: Single file"
else
    echo "📁 Input folder: $INPUT_FOLDER"
    echo "🔀 Mode: Batch processing"
fi
if [ -n "$OUTPUT_FOLDER" ]; then
    echo "📂 Output folder: $OUTPUT_FOLDER"
fi
echo "🎨 Testing ${#LORAS[@]} LoRA styles"
echo ""

START_TIME=$(date +%s)

# Iterate through each LoRA
for LORA in "${LORAS[@]}"; do
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "🎨 Processing with LoRA: $LORA"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    
    LORA_START=$(date +%s)
    
    # Build command with appropriate arguments
    CMD="python core/lora_transformer.py --lora \"$LORA\""
    
    if [ -n "$INPUT_FILE" ]; then
        # Single file mode
        CMD="$CMD --file \"$INPUT_FILE\""
    else
        # Batch mode
        CMD="$CMD --batch --input-folder \"$INPUT_FOLDER\""
    fi
    
    if [ -n "$OUTPUT_FOLDER" ]; then
        CMD="$CMD --output-folder \"$OUTPUT_FOLDER\""
    fi
    
    # Run the processing
    eval $CMD
    
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
