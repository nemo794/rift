#!/bin/bash
################################################################################
# MAAP DPS run script for the rift NISAR end-to-end algorithm.
#
# DPS convention: inputs staged in ./input, outputs captured from ./output.
# Positional args (from algorithm_config.yaml), in order:
#   x_spacing y_spacing native resampling threshold pols keep_intermediates
################################################################################
set -euo pipefail

basedir=$(dirname "$(readlink -f "$0")")
INPUT_DIR="${PWD}/input"
OUTPUT_DIR="${PWD}/output"
mkdir -p "${OUTPUT_DIR}"

X_SPACING="${1:-5}"
Y_SPACING="${2:-5}"
NATIVE="${3:-false}"
RESAMPLING="${4:-nearest}"
THRESHOLD="${5:-0.5}"
POLS="${6:-}"
KEEP="${7:-false}"

GSLC=$(find "${INPUT_DIR}" -maxdepth 1 -iname "NISAR_*GSLC*.h5" | head -n 1)
if [ -z "${GSLC}" ]; then
    echo "ERROR: no NISAR GSLC (.h5) found in ${INPUT_DIR}" >&2
    exit 1
fi

EXTRA=()
[ "${NATIVE}" = "true" ] && EXTRA+=(--native)
[ "${KEEP}" = "true" ] && EXTRA+=(--keep-intermediates)
[ -n "${POLS}" ] && EXTRA+=(--pols "[${POLS}]")

conda run -n rift rift nisar-e2e \
    --gslc "${GSLC}" \
    --output "${OUTPUT_DIR}" \
    --x-spacing "${X_SPACING}" \
    --y-spacing "${Y_SPACING}" \
    --resampling "${RESAMPLING}" \
    --threshold "${THRESHOLD}" \
    "${EXTRA[@]}"
