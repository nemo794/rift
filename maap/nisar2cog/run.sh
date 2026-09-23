#!/usr/bin/env bash
################################################################################
# MAAP DPS run script for the rift nisar2cog OGC algorithm.
#
# DPS passes the registered inputs as --name value pairs. This wrapper creates the
# output/ directory and hands off to the Python entrypoint inside the conda env.
################################################################################
set -euo pipefail

basedir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
OUTDIR="${USER_OUTPUT_DIR:-${OUTPUT_DIR:-output}}"
mkdir -p "${OUTDIR}"

conda run --live-stream -p /opt/conda/envs/rift_nisar2cog \
  python "${basedir}/nisar2cog_dps.py" --out_dir "${OUTDIR}" "$@"

find "${OUTDIR}" -maxdepth 2 -print || true
