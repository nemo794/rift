#!/usr/bin/env bash
################################################################################
# MAAP DPS run script for the rift nisar-e2e OGC algorithm.
#
# DPS passes the registered inputs as --name value pairs. This wrapper creates the
# output/ directory and hands off to the Python entrypoint inside the geocoding
# conda env (rift_nisar2cog). That entrypoint runs rift nisar2cog, then shells out
# to the `crevasse` env for the ML inference step (both write to output/).
################################################################################
set -euo pipefail

basedir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
OUTDIR="${USER_OUTPUT_DIR:-${OUTPUT_DIR:-output}}"
mkdir -p "${OUTDIR}"

conda run --live-stream -p /opt/conda/envs/rift_nisar2cog \
  python "${basedir}/nisar_e2e_dps.py" --out_dir "${OUTDIR}" "$@"

find "${OUTDIR}" -maxdepth 2 -print || true
