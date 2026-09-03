#!/bin/bash
################################################################################
# MAAP DPS run script for the rift BIOMASS end-to-end algorithm.
#
# DPS convention: inputs are staged in ./input, outputs are captured from ./output.
# Positional args (from algorithm_config.yaml) arrive after the file inputs, in order:
#   x_spacing y_spacing native margin threshold pols keep_intermediates
################################################################################
set -euo pipefail

basedir=$(dirname "$(readlink -f "$0")")
INPUT_DIR="${PWD}/input"
OUTPUT_DIR="${PWD}/output"
mkdir -p "${OUTPUT_DIR}"

# Positional parameters with defaults.
X_SPACING="${1:-5}"
Y_SPACING="${2:-5}"
NATIVE="${3:-false}"
MARGIN="${4:-5000}"
THRESHOLD="${5:-0.5}"
POLS="${6:-HH}"
KEEP="${7:-false}"

# Locate the granule (.zip) and optional DEM in the staged input directory.
GRANULE=$(find "${INPUT_DIR}" -maxdepth 1 -iname "BIO_*" | head -n 1)
DEM=$(find "${INPUT_DIR}" -maxdepth 1 -iname "*.tif" | head -n 1 || true)

if [ -z "${GRANULE}" ]; then
    echo "ERROR: no BIOMASS granule (BIO_*) found in ${INPUT_DIR}" >&2
    exit 1
fi

# Build optional flags.
EXTRA=()
[ "${NATIVE}" = "true" ] && EXTRA+=(--native)
[ "${KEEP}" = "true" ] && EXTRA+=(--keep-intermediates)
[ -n "${DEM}" ] && EXTRA+=(--dem "${DEM}")

# jsonargparse list syntax for --pols (comma-separated → [a,b]).
POLS_ARG="[${POLS}]"

conda run -n rift rift biomass-e2e \
    --granule "${GRANULE}" \
    --output "${OUTPUT_DIR}" \
    --x-spacing "${X_SPACING}" \
    --y-spacing "${Y_SPACING}" \
    --margin "${MARGIN}" \
    --threshold "${THRESHOLD}" \
    --pols "${POLS_ARG}" \
    "${EXTRA[@]}"
