#!/usr/bin/env bash
################################################################################
# MAAP build script for the rift biomass2cog OGC algorithm.
#
# Runs on MAAP's build infrastructure on top of maap_base (which ships maap-py
# plus the DPS credential plumbing). Creates the heavy isce3/biomass conda env,
# installs biomass-reader (from GitHub, not on conda), and installs the rift
# package into it.
################################################################################
set -euo pipefail

basedir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# repo root = .../rift (this script lives in rift/maap/biomass2cog/)
repo_root="$(cd "${basedir}/../.." && pwd -P)"

# Entry scripts must be executable in the built image (else DPS exits 126).
chmod +x "${basedir}/run.sh" "${basedir}/build.sh"

ENV_PREFIX="/opt/conda/envs/rift_biomass2cog"

conda env remove -p "${ENV_PREFIX}" -y || true
conda env create -f "${basedir}/env.yml" --prefix "${ENV_PREFIX}"

# biomass-reader parses BIOMASS L1A products into isce3 objects; not on conda-forge.
work="$(mktemp -d)"
git clone --depth 1 https://github.com/scottstanie/biomass-reader.git "${work}/biomass-reader"
conda run -p "${ENV_PREFIX}" pip install --no-cache-dir "${work}/biomass-reader[ionosphere]"

# Install rift itself into the env.
conda run -p "${ENV_PREFIX}" pip install --no-cache-dir "${repo_root}"

conda clean -afy
rm -rf "${work}"

# Sanity check the runtime.
conda run -p "${ENV_PREFIX}" python - <<'PY'
import isce3, rasterio, h5py, numpy, scipy, pyproj
import obstore, pystac_client, sardem
from biomass_reader import BiomassSlc
import rift
print("Environment validation successful.")
print("isce3", isce3.__version__, "| rasterio", rasterio.__version__)
print("obstore", obstore.__version__, "| pystac_client", pystac_client.__version__)
PY

echo "✓ rift biomass2cog environment ready at ${ENV_PREFIX}"
