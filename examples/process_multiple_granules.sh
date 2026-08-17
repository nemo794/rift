#!/bin/bash
#
# Example: Process multiple BIOMASS granules over the same geographic area
#
# This script demonstrates how to:
# 1. Compute a shared geogrid from the first granule (with generous margin)
# 2. Geocode all granules to the same grid
# 3. Validate the alignment
#
# All output COGs will have perfectly aligned chunks and can be efficiently mosaicked.

set -e  # Exit on error

# Configuration
GRANULE_DIR="/path/to/biomass/granules"
DEM_FILE="/path/to/dem_epsg3031.tif"
OUTPUT_DIR="./geocoded_outputs"
POLARIZATION="HH"
MARGIN=10000  # 10 km margin to ensure all granules fit

# Create output directory
mkdir -p "$OUTPUT_DIR"

echo "=========================================="
echo "Processing Multiple BIOMASS Granules"
echo "=========================================="
echo ""

# Find all BIOMASS granules
GRANULES=($(find "$GRANULE_DIR" -maxdepth 1 -name "BIO_*" -type d))
NUM_GRANULES=${#GRANULES[@]}

if [ $NUM_GRANULES -eq 0 ]; then
    echo "ERROR: No BIOMASS granules found in $GRANULE_DIR"
    exit 1
fi

echo "Found $NUM_GRANULES granule(s)"
echo ""

# Step 1: Compute geogrid from first granule
echo "=========================================="
echo "Step 1: Computing shared geogrid"
echo "=========================================="
FIRST_GRANULE="${GRANULES[0]}"
GEOGRID_FILE="$OUTPUT_DIR/shared_geogrid.json"

python src/compute_biomass_geogrid.py \
    "$FIRST_GRANULE" \
    --polarization "$POLARIZATION" \
    --margin "$MARGIN" \
    --output "$GEOGRID_FILE"

echo ""
echo "✓ Geogrid saved to: $GEOGRID_FILE"
echo ""

# Step 2: Geocode all granules to the shared grid
echo "=========================================="
echo "Step 2: Geocoding all granules"
echo "=========================================="

for i in "${!GRANULES[@]}"; do
    GRANULE="${GRANULES[$i]}"
    GRANULE_NAME=$(basename "$GRANULE")
    OUTPUT_FILE="$OUTPUT_DIR/${GRANULE_NAME}_${POLARIZATION}.tif"

    echo ""
    echo "------------------------------------------"
    echo "Processing [$((i+1))/$NUM_GRANULES]: $GRANULE_NAME"
    echo "------------------------------------------"

    python src/geocode_biomass_custom_grid.py \
        --biomass-granule "$GRANULE" \
        --geogrid "$GEOGRID_FILE" \
        --dem "$DEM_FILE" \
        --output "$OUTPUT_FILE" \
        --polarization "$POLARIZATION"

    echo "✓ Saved: $OUTPUT_FILE"
done

echo ""
echo "=========================================="
echo "Step 3: Validating grid alignment"
echo "=========================================="

python src/validate_grid_alignment.py "$GEOGRID_FILE"

echo ""
echo "=========================================="
echo "Processing Complete!"
echo "=========================================="
echo ""
echo "Output files:"
ls -lh "$OUTPUT_DIR"/*.tif

echo ""
echo "All COGs have aligned chunks and can be mosaicked with:"
echo "  gdal_merge.py -o mosaic.tif $OUTPUT_DIR/*_${POLARIZATION}.tif"
echo ""
echo "Or create a VRT (virtual mosaic) with:"
echo "  gdalbuildvrt mosaic.vrt $OUTPUT_DIR/*_${POLARIZATION}.tif"
