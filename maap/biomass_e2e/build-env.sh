#!/bin/bash
################################################################################
# MAAP DPS build script for the rift BIOMASS end-to-end algorithm.
#
# Installs the conda environment, biomass-reader (from GitHub, not on conda), and
# the rift package itself. Run once at algorithm registration / image build time.
################################################################################
set -euo pipefail

basedir=$(dirname "$(readlink -f "$0")")
# repo root = .../rift (this script lives in rift/maap/biomass_e2e/)
repo_root=$(cd "${basedir}/../.." && pwd)

cd "${repo_root}"

# 1. Create/refresh the conda environment.
conda env create -f environment.yaml || conda env update -f environment.yaml

# 2. biomass-reader (required for the BIOMASS workflow; not on conda-forge).
if [ ! -d biomass-reader ]; then
    git clone https://github.com/scottstanie/biomass-reader.git
fi
conda run -n rift pip install -e './biomass-reader[ionosphere]'

# 3. Install rift.
conda run -n rift pip install -e .

echo "✓ rift BIOMASS e2e environment ready"
