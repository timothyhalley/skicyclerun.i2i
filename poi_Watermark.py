"""CLI entry point — thin shim over core.poi_watermark_engine."""
from core.poi_watermark_engine import process_folder, process_photo  # noqa: F401

if __name__ == "__main__":
    import sys

    folder = sys.argv[1] if len(sys.argv) > 1 else "/Volumes/MySSD/skicyclerun.i2i/pipeline/albums"
    results = process_folder(folder, style="emoji")

    print("\n=== Batch Processing Summary ===")
    print(f"Total photos processed: {len(results)}")
