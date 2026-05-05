#!/bin/bash

# Local authoritative source
SRC="/Volumes/MySSD/skicyclerun.i2i/pipeline/"

# Remote destination on Adventum
DEST="/Volumes/Adventum_MySSD_Public/pipeline/"

# Run rsync mirror (local → remote)
rsync -avh --delete --progress "$SRC" "$DEST"
