#!/bin/zsh

# Night Batch Run Script
# Prevents Mac from sleeping during long batch processing runs
# Uses caffeinate to keep the system awake while processing images

set -e  # Exit on error

# Display usage information
usage() {
    echo "Usage: $0 --lora <lora_name> --input <input_folder> [options]"
    echo ""
    echo "Required:"
    echo "  --lora <name>         LoRA style to use (e.g., Ghibli, Jojo, Super_Pencil)"
    echo "  --input <folder>      Input folder containing images to process"
    echo ""
    echo "Optional:"
    echo "  --output <folder>     Output folder (default: $SKICYCLERUN_LIB_ROOT/images/lora_processed)"
    echo "  --verbose             Enable verbose output"
    echo "  --debug               Enable debug mode"
    echo ""
    echo "Examples:"
    echo "  $0 --lora Super_Pencil --input $SKICYCLERUN_LIB_ROOT/pipeline/scaled"
    echo "  $0 --lora Jojo --input ~/Pictures/batch1 --verbose"
    echo ""
    exit 1
}

# Check if no arguments provided
if [ $# -eq 0 ]; then
    usage
fi

# Parse arguments
LORA=""
INPUT=""
OUTPUT=""
VERBOSE=""
DEBUG=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --lora)
            LORA="$2"
            shift 2
            ;;
        --input)
            INPUT="$2"
            shift 2
            ;;
        --output)
            OUTPUT="$2"
            shift 2
            ;;
        --verbose)
            VERBOSE="--verbose"
            shift
            ;;
        --debug)
            DEBUG="--debug"
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "❌ Unknown option: $1"
            usage
            ;;
    esac
done

# Validate required arguments
if [ -z "$LORA" ]; then
    echo "❌ Error: --lora is required"
    usage
fi

if [ -z "$INPUT" ]; then
    echo "❌ Error: --input is required"
    usage
fi

# Check if input folder exists
if [ ! -d "$INPUT" ]; then
    echo "❌ Error: Input folder does not exist: $INPUT"
    exit 1
fi

# Build the command
CMD="python core/lora_transformer.py --lora \"$LORA\" --file \"$INPUT\" --batch"

if [ -n "$OUTPUT" ]; then
    CMD="$CMD --output-folder \"$OUTPUT\""
fi

if [ -n "$VERBOSE" ]; then
    CMD="$CMD $VERBOSE"
fi

if [ -n "$DEBUG" ]; then
    CMD="$CMD $DEBUG"
fi

# Display run information
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🌙 Night Batch Processing"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎨 LoRA Style: $LORA"
echo "📁 Input: $INPUT"
if [ -n "$OUTPUT" ]; then
    echo "📤 Output: $OUTPUT"
fi
echo "💻 System will stay awake during processing"
echo "⏰ Started: $(date '+%Y-%m-%d %H:%M:%S')"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🚀 Running: caffeinate -i $CMD"
echo ""

# Run with caffeinate to prevent sleep
# -i: Prevent system idle sleep
caffeinate -i eval $CMD

EXIT_CODE=$?

# Display completion information
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ $EXIT_CODE -eq 0 ]; then
    echo "✅ Batch processing completed successfully"
else
    echo "❌ Batch processing failed with exit code: $EXIT_CODE"
fi
echo "⏰ Finished: $(date '+%Y-%m-%d %H:%M:%S')"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

exit $EXIT_CODE
