#!/usr/bin/env bash
# Migration script to restructure existing directories to new pipeline layout
# Usage: ./migrate_to_pipeline_structure.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  SkiCycleRun Pipeline Structure Migration                          ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check for required environment variable
if [ -z "$SKICYCLERUN_LIB_ROOT" ]; then
    echo -e "${RED}❌ ERROR: SKICYCLERUN_LIB_ROOT not set${NC}"
    echo -e "${YELLOW}Please run: source ./env_setup.sh <images_root> [huggingface_cache]${NC}"
    exit 1
fi

echo -e "${GREEN}✓ SKICYCLERUN_LIB_ROOT: ${SKICYCLERUN_LIB_ROOT}${NC}"
echo ""

# Define old and new paths
OLD_ALBUMS="$SKICYCLERUN_LIB_ROOT/images/albums"
OLD_SCALED="$SKICYCLERUN_LIB_ROOT/images/scaled"
OLD_LORA="$SKICYCLERUN_LIB_ROOT/images/lora_processed"
OLD_FINAL="$SKICYCLERUN_LIB_ROOT/images/lora_final"
OLD_METADATA="$SKICYCLERUN_LIB_ROOT/metadata"

NEW_PIPELINE="$SKICYCLERUN_LIB_ROOT/pipeline"
NEW_ARCHIVE_ALBUMS="$NEW_PIPELINE/archive/albums"
NEW_ARCHIVE_METADATA="$NEW_PIPELINE/archive/metadata"
NEW_ALBUMS="$NEW_PIPELINE/albums"
NEW_METADATA="$NEW_PIPELINE/metadata"
NEW_SCALED="$NEW_PIPELINE/scaled"
NEW_LORA="$NEW_PIPELINE/lora_processed"
NEW_WATERMARKED="$NEW_PIPELINE/watermarked_final"

# Function to safely move directory
move_dir() {
    local src="$1"
    local dest="$2"
    local desc="$3"
    
    if [ -d "$src" ]; then
        echo -e "${YELLOW}→ Moving $desc...${NC}"
        echo -e "   From: $src"
        echo -e "   To:   $dest"
        
        # Create parent directory
        mkdir -p "$(dirname "$dest")"
        
        # Move directory
        mv "$src" "$dest"
        echo -e "${GREEN}   ✓ Done${NC}"
    else
        echo -e "${BLUE}   ℹ $desc not found (skipping)${NC}"
    fi
    echo ""
}

# Function to copy and version metadata
version_metadata() {
    local src="$1"
    local dest_dir="$2"
    
    if [ -f "$src" ]; then
        local timestamp=$(date +%Y%m%d_%H%M%S)
        local version=1
        local dest="$dest_dir/master_v${version}_${timestamp}.json"
        
        echo -e "${YELLOW}→ Versioning metadata...${NC}"
        echo -e "   From: $src"
        echo -e "   To:   $dest"
        
        mkdir -p "$dest_dir"
        cp "$src" "$dest"
        echo -e "${GREEN}   ✓ Metadata backed up${NC}"
    else
        echo -e "${BLUE}   ℹ No metadata file to version${NC}"
    fi
    echo ""
}

echo -e "${YELLOW}This script will restructure your directories as follows:${NC}"
echo ""
echo -e "OLD STRUCTURE → NEW STRUCTURE"
echo -e "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo -e "images/albums/          → pipeline/archive/albums/"
echo -e "images/scaled/          → pipeline/scaled/"
echo -e "images/lora_processed/  → pipeline/lora_processed/"
echo -e "images/lora_final/      → pipeline/watermarked_final/"
echo -e "metadata/master.json    → pipeline/archive/metadata/master_v1_*.json"
echo -e "                        → pipeline/metadata/ (new empty)"
echo ""
echo -e "${YELLOW}⚠️  WARNING: This will MOVE directories (not copy)${NC}"
echo -e "${YELLOW}⚠️  Ensure you have backups before proceeding!${NC}"
echo ""

read -p "Continue with migration? [y/N]: " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${RED}Migration cancelled${NC}"
    exit 0
fi

echo ""
echo -e "${BLUE}╔════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Starting Migration...                                             ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Create new pipeline structure
echo -e "${YELLOW}→ Creating new pipeline directory structure...${NC}"
mkdir -p "$NEW_ARCHIVE_ALBUMS"
mkdir -p "$NEW_ARCHIVE_METADATA"
mkdir -p "$NEW_ALBUMS"
mkdir -p "$NEW_METADATA"
mkdir -p "$NEW_SCALED"
mkdir -p "$NEW_LORA"
mkdir -p "$NEW_WATERMARKED"
echo -e "${GREEN}   ✓ Directory structure created${NC}"
echo ""

# Move old albums to archive
move_dir "$OLD_ALBUMS" "$NEW_ARCHIVE_ALBUMS" "Old albums to archive"

# Version existing metadata
version_metadata "$OLD_METADATA/master.json" "$NEW_ARCHIVE_METADATA"

# Move scaled images
move_dir "$OLD_SCALED" "$NEW_SCALED" "Scaled images"

# Move LoRA processed images
move_dir "$OLD_LORA" "$NEW_LORA" "LoRA processed images"

# Move final images to watermarked_final
move_dir "$OLD_FINAL" "$NEW_WATERMARKED" "Final watermarked images"

# Copy geocode cache if exists
if [ -f "$OLD_METADATA/geocode_cache.json" ]; then
    echo -e "${YELLOW}→ Copying geocode cache...${NC}"
    cp "$OLD_METADATA/geocode_cache.json" "$NEW_METADATA/"
    echo -e "${GREEN}   ✓ Geocode cache copied${NC}"
    echo ""
fi

# Summary
echo ""
echo -e "${BLUE}╔════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  Migration Complete!                                               ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}✓ Directory structure migrated successfully${NC}"
echo ""
echo -e "${YELLOW}New structure:${NC}"
echo -e "  📁 $NEW_PIPELINE"
echo -e "     ├── archive/"
echo -e "     │   ├── albums/       (old albums)"
echo -e "     │   └── metadata/     (versioned master.json)"
echo -e "     ├── albums/           (ready for new exports)"
echo -e "     ├── metadata/         (for new extractions)"
echo -e "     ├── scaled/"
echo -e "     ├── lora_processed/"
echo -e "     └── watermarked_final/"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo -e "  1. Review migrated directories"
echo -e "  2. Export NEW albums: ${BLUE}osascript scripts/osxPhotoExporter.scpt${NC}"
echo -e "  3. Run pipeline: ${BLUE}python pipeline.py --yes${NC}"
echo ""
echo -e "${YELLOW}Old directories that can be removed:${NC}"
echo -e "  • $SKICYCLERUN_LIB_ROOT/images/ (if empty)"
echo -e "  • $SKICYCLERUN_LIB_ROOT/metadata/ (if empty)"
echo ""
