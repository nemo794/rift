#!/bin/bash
################################################################################
# MAAP DPS build script for the rift NISAR end-to-end algorithm.
#
# Installs the conda environment and the rift package. biomass-reader is NOT needed
# for the NISAR workflow (no ISCE3 radar geocoding), so it is skipped here.
################################################################################
set -euo pipefail

basedir=$(dirname "$(readlink -f "$0")")
repo_root=$(cd "${basedir}/../.." && pwd)

cd "${repo_root}"

conda env create -f environment.yaml || conda env update -f environment.yaml
conda run -n rift pip install -e .

echo "✓ rift NISAR e2e environment ready"
