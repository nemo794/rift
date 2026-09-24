#!/usr/bin/env bash
################################################################################
# MAAP build script for the rift nisar-e2e OGC algorithm.
#
# Runs on MAAP's build infrastructure on top of maap_base (which can pull the
# private mas.maap-project.org base image and ships maap-py). Creates TWO conda
# envs in the image:
#
#   rift_nisar2cog : slim geocoding env (rift nisar2cog, no isce3)
#   crevasse       : the nisar-crevasse gate + U-Net inference env (torch)
#
# and bakes the large NISAR U-Net checkpoint from my-public-bucket into the
# cloned nisar-crevasse repo at the exact nested path its predictor loads by
# default (unet_predict.py's DEFAULT_CHECKPOINT). No AWS creds needed: the model
# is fetched over anonymous public HTTPS.
################################################################################
set -euo pipefail

basedir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
# repo root = .../rift (this script lives in rift/maap/nisar_e2e/)
repo_root="$(cd "${basedir}/../.." && pwd -P)"

# Entry scripts must be executable in the built image (else DPS exits 126).
chmod +x "${basedir}/run.sh" "${basedir}/build.sh"

# --------------------------------------------------------------------------------------
# Env A: slim geocoding (rift nisar2cog, no isce3)
# --------------------------------------------------------------------------------------
ENV_PREFIX="/opt/conda/envs/rift_nisar2cog"

conda env remove -p "${ENV_PREFIX}" -y || true
conda env create -f "${basedir}/env.yml" --prefix "${ENV_PREFIX}"

# Install rift itself into the geocoding env.
conda run -p "${ENV_PREFIX}" pip install --no-cache-dir "${repo_root}"

# --------------------------------------------------------------------------------------
# Env B: nisar-crevasse gate + U-Net inference (torch)
# --------------------------------------------------------------------------------------
# Clone the merged crevasse repo (both sensors; we only drive the NISAR side).
CREVASSE_REPO="${CREVASSE_REPO:-https://github.com/nemo794/nisar-crevasse.git}"
CREVASSE_REF="${CREVASSE_REF:-main}"
CREVASSE_DIR="${CREVASSE_DIR:-/opt/nisar-crevasse}"

rm -rf "${CREVASSE_DIR}"
git clone --depth 1 --branch "${CREVASSE_REF}" "${CREVASSE_REPO}" "${CREVASSE_DIR}"

# The crevasse env is named `crevasse` in its own environment.yml.
CREVASSE_ENV_PREFIX="/opt/conda/envs/crevasse"
conda env remove -p "${CREVASSE_ENV_PREFIX}" -y || true
conda env create -f "${CREVASSE_DIR}/environment.yml" --prefix "${CREVASSE_ENV_PREFIX}"

# Editable install so the console scripts (crevasse-export-geotiff) resolve, and so the
# default model path (relative to the package source) points inside this clone.
conda run -p "${CREVASSE_ENV_PREFIX}" pip install --no-cache-dir -e "${CREVASSE_DIR}"

# --------------------------------------------------------------------------------------
# Bake the large NISAR U-Net checkpoint from my-public-bucket into the clone.
# --------------------------------------------------------------------------------------
# my-public-bucket = s3://maap-ops-workspace/shared/<username>/...  It is NOT anonymously
# readable over HTTPS (returns 403), so fetch it with the workspace's MAAP AWS credentials
# via `aws s3 cp` — the same credential context that lets `aws s3 cp s3://... .` work in a
# MAAP workspace, and that MAAP's build infra runs under.
# Uploaded to: my-public-bucket/crevasse_unet_models/nisar/unet_best.safetensors
MODEL_S3_URI="${MODEL_S3_URI:-s3://maap-ops-workspace/shared/niemoell/crevasse_unet_models/nisar/unet_best.safetensors}"
# Must match unet_predict.py's DEFAULT_CHECKPOINT (models/nisar/unet/<run>/unet_best.safetensors).
MODEL_DEST="${CREVASSE_DIR}/models/nisar/unet/unet_025_019_f421_meansoft_g3/unet_best.safetensors"

mkdir -p "$(dirname "${MODEL_DEST}")"
echo "Fetching NISAR U-Net checkpoint: ${MODEL_S3_URI}"
if command -v aws >/dev/null 2>&1; then
  aws s3 cp "${MODEL_S3_URI}" "${MODEL_DEST}"
else
  # No aws CLI on PATH: fall back to boto3 (ships in the geocoding env) using the same
  # ambient AWS credentials.
  echo "aws CLI not found; falling back to boto3 in the rift_nisar2cog env."
  conda run -p "${ENV_PREFIX}" python - "${MODEL_S3_URI}" "${MODEL_DEST}" <<'PY'
import sys, boto3
uri, dest = sys.argv[1], sys.argv[2]
assert uri.startswith("s3://"), uri
bucket, key = uri[5:].split("/", 1)
boto3.client("s3").download_file(bucket, key, dest)
print(f"downloaded s3://{bucket}/{key} -> {dest}")
PY
fi
echo "  -> ${MODEL_DEST} ($(du -h "${MODEL_DEST}" | cut -f1))"

conda clean -afy

# --------------------------------------------------------------------------------------
# Sanity checks
# --------------------------------------------------------------------------------------
conda run -p "${ENV_PREFIX}" python - <<'PY'
import rasterio, h5py, numpy, scipy, pyproj, s3fs, earthaccess
import rift
print("Geocoding env OK — rasterio", rasterio.__version__, "| h5py", h5py.__version__)
PY

conda run -p "${CREVASSE_ENV_PREFIX}" python - <<'PY'
import torch
from crevasse.nisar.unet_predict import DEFAULT_CHECKPOINT
p = str(DEFAULT_CHECKPOINT) + ".safetensors"
import os
assert os.path.exists(p), f"baked U-Net checkpoint missing at {p}"
print("Crevasse env OK — torch", torch.__version__)
print("U-Net checkpoint present:", p)
PY

echo "✓ rift nisar-e2e image ready (envs: rift_nisar2cog + crevasse; model baked)"
