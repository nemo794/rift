#!/usr/bin/env bash
################################################################################
# MAAP build script for the rift nisar2cog OGC algorithm.
#
# Runs on MAAP's build infrastructure on top of maap_base (which can pull the
# private mas.maap-project.org base image and ships maap-py). Creates a conda env
# and installs the rift package into it. No isce3 (NISAR path doesn't need it).
################################################################################
set -euo pipefail

basedir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# repo root = .../rift (this script lives in rift/maap/nisar2cog/)
repo_root="$(cd "${basedir}/../.." && pwd -P)"

# Entry scripts must be executable in the built image (else DPS exits 126).
chmod +x "${basedir}/run.sh" "${basedir}/build.sh"

ENV_PREFIX="/opt/conda/envs/rift_nisar2cog"

conda env remove -p "${ENV_PREFIX}" -y || true
conda env create -f "${basedir}/env.yml" --prefix "${ENV_PREFIX}"

# Install rift itself into the env.
conda run -p "${ENV_PREFIX}" pip install --no-cache-dir "${repo_root}"

conda clean -afy

# Sanity check the runtime.
conda run -p "${ENV_PREFIX}" python - <<'PY'
import rasterio, h5py, numpy, scipy, pyproj, s3fs, earthaccess
import rift
print("Environment validation successful.")
print("rasterio", rasterio.__version__, "| h5py", h5py.__version__)
print("s3fs", s3fs.__version__, "| earthaccess", earthaccess.__version__)
PY

echo "✓ rift nisar2cog environment ready at ${ENV_PREFIX}"
