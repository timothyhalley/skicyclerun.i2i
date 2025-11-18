#!/usr/bin/env python3
"""Legacy master catalog builder.

This script is intentionally kept as a stub because the pipeline now writes
directly to `MasterStore` (see ``core/master_store.py``) and no longer produces
intermediate ``catalog.json`` or ``geocode_cache.json`` artifacts.

Attempting to run this script will raise a helpful error so callers know to use
the modern workflow.
"""

import sys


def _main() -> None:
    raise RuntimeError(
        "master_catalog_builder.py is deprecated. The pipeline maintains its"
        " master data via MasterStore; rerun the pipeline metadata and"
        " geocode sweep stages instead of this legacy script."
    )


if __name__ == "__main__":
    try:
        _main()
    except RuntimeError as exc:
        print(f"❌ {exc}")
        sys.exit(1)
