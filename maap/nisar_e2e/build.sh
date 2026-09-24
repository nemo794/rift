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
# default (unet_predict.py's DEFAULT_CHECKPOINT). my-public-bucket is NOT
# anonymously public (403 over HTTPS), so the model is pulled with credentials
# (MAAP workspace creds first, then the default AWS chain) via boto3.
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
# Built first (it is the cheaper solve) so the credentialed model fetch below can run inside
# it — it ships boto3 + maap-py, and the base maap_base env does not.
ENV_PREFIX="/opt/conda/envs/rift_nisar2cog"

conda env remove -p "${ENV_PREFIX}" -y || true
conda env create -f "${basedir}/env.yml" --prefix "${ENV_PREFIX}"

# Install rift itself into the geocoding env.
conda run -p "${ENV_PREFIX}" pip install --no-cache-dir "${repo_root}"

# --------------------------------------------------------------------------------------
# Fetch the large NISAR U-Net checkpoint from my-public-bucket (FAIL EARLY).
# --------------------------------------------------------------------------------------
# The credentialed S3 fetch is the most failure-prone step, so do it right after the cheap
# geocoding env — before the heavy crevasse solve and the clone — and stage it to a temp
# file. It is copied into the clone at its final nested path once that exists (see "Bake the
# model" below).
#
# my-public-bucket is NOT anonymously public (403 over HTTPS), so fetch with credentials:
# MAAP workspace credentials first, then the default AWS chain. Runs in the geocoding env
# (has boto3 + maap-py).
MODEL_S3_URI="${MODEL_S3_URI:-s3://maap-ops-workspace/shared/niemoell/crevasse_unet_models/nisar/unet_best.safetensors}"
MODEL_STAGED="$(mktemp /tmp/unet_best.XXXXXX.safetensors)"

echo "Fetching NISAR U-Net checkpoint: ${MODEL_S3_URI}"

# NOTE: write the fetcher to a real file and pass args — do NOT pipe a heredoc into
# `conda run ... python -`. conda run does not forward stdin to the child, so `python -`
# would read an empty program and silently no-op (the bug that shipped an empty model).
FETCH_PY="$(mktemp /tmp/fetch_model.XXXXXX.py)"
cat > "${FETCH_PY}" <<'PY'
import sys, boto3

uri, dest = sys.argv[1], sys.argv[2]
assert uri.startswith("s3://"), uri
bucket, key = uri[5:].split("/", 1)


def _maap_client():
    """boto3 S3 client using MAAP workspace credentials (maap-py ships on maap_base)."""
    from maap.maap import MAAP
    c = MAAP().aws.workspace_bucket_credentials()["credentials"]
    return boto3.client(
        "s3",
        aws_access_key_id=c["aws_access_key_id"],
        aws_secret_access_key=c["aws_secret_access_key"],
        aws_session_token=c["aws_session_token"],
    )


last = None
for label, make in (("maap-workspace-creds", _maap_client),
                    ("default-aws-chain", lambda: boto3.client("s3"))):
    try:
        print(f"  trying {label} ...", flush=True)
        make().download_file(bucket, key, dest)
        print(f"  downloaded via {label}: s3://{bucket}/{key} -> {dest}", flush=True)
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        last = exc
        print(f"  {label} failed: {type(exc).__name__}: {exc}", flush=True)

print(f"ERROR: could not download {uri}: {last}", file=sys.stderr)
sys.exit(1)
PY

# Run in the geocoding env (has boto3 + maap-py). Fails the build (set -e) on nonzero exit.
conda run -p "${ENV_PREFIX}" python "${FETCH_PY}" "${MODEL_S3_URI}" "${MODEL_STAGED}"
rm -f "${FETCH_PY}"

# Hard-fail immediately if the model is missing or empty — before the heavy crevasse solve.
if [ ! -s "${MODEL_STAGED}" ]; then
  echo "ERROR: model not present after fetch: ${MODEL_STAGED}" >&2
  exit 1
fi
echo "  staged -> ${MODEL_STAGED} ($(du -h "${MODEL_STAGED}" | cut -f1))"

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
# Bake the staged U-Net checkpoint into the clone at its final nested path.
# --------------------------------------------------------------------------------------
# Must match unet_predict.py's DEFAULT_CHECKPOINT (models/nisar/unet/<run>/unet_best.safetensors).
MODEL_DEST="${CREVASSE_DIR}/models/nisar/unet/unet_025_019_f421_meansoft_g3/unet_best.safetensors"

mkdir -p "$(dirname "${MODEL_DEST}")"
mv "${MODEL_STAGED}" "${MODEL_DEST}"

# Hard-fail if the model is missing or empty (belt-and-suspenders around the copy above).
if [ ! -s "${MODEL_DEST}" ]; then
  echo "ERROR: model not present after copy: ${MODEL_DEST}" >&2
  exit 1
fi
echo "  baked -> ${MODEL_DEST} ($(du -h "${MODEL_DEST}" | cut -f1))"

conda clean -afy

# --------------------------------------------------------------------------------------
# Sanity checks (write to files; never pipe via `conda run ... python -` — see note above)
# --------------------------------------------------------------------------------------
CHECK_GEO_PY="$(mktemp /tmp/check_geo.XXXXXX.py)"
cat > "${CHECK_GEO_PY}" <<'PY'
import rasterio, h5py, numpy, scipy, pyproj, s3fs, earthaccess
import rift
print("Geocoding env OK — rasterio", rasterio.__version__, "| h5py", h5py.__version__)
PY
conda run -p "${ENV_PREFIX}" python "${CHECK_GEO_PY}"
rm -f "${CHECK_GEO_PY}"

CHECK_ML_PY="$(mktemp /tmp/check_ml.XXXXXX.py)"
cat > "${CHECK_ML_PY}" <<'PY'
import os
import torch
from crevasse.nisar.unet_predict import DEFAULT_CHECKPOINT
p = str(DEFAULT_CHECKPOINT) + ".safetensors"
assert os.path.exists(p), f"baked U-Net checkpoint missing at {p}"
print("Crevasse env OK — torch", torch.__version__)
print("U-Net checkpoint present:", p)
PY
conda run -p "${CREVASSE_ENV_PREFIX}" python "${CHECK_ML_PY}"
rm -f "${CHECK_ML_PY}"

echo "✓ rift nisar-e2e image ready (envs: rift_nisar2cog + crevasse; model baked)"
