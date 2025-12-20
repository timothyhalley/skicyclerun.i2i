#!/bin/bash
#
# List available AWS Location Service Place Indexes
#

echo "📍 Available AWS Location Service Place Indexes:"
echo ""

aws location list-place-indexes --output table
