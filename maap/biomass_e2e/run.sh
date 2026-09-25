#!/usr/bin/env bash
################################################################################
# MAAP DPS run script for the rift biomass-e2e OGC algorithm.
#
# DPS passes the registered inputs as --name value pairs. This wrapper creates the
# output/ directory and hands off to the Python entrypoint inside the geocoding
# conda env (rift_biomass2cog). That entrypoint fetches the ESA granule, runs
# rift biomass2cog, derives per-pol *_intensity.tif COGs (scripts/make_pwr_cogs.py),
# then shells out to the `crevasse` env for the BIOMASS gate + U-Net inference step
# (all write to output/).
################################################################################
set -euo pipefail

basedir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
OUTDIR="${USER_OUTPUT_DIR:-${OUTPUT_DIR:-output}}"
mkdir -p "${OUTDIR}"

conda run --live-stream -p /opt/conda/envs/rift_biomass2cog \
  python "${basedir}/biomass_e2e_dps.py" --out_dir "${OUTDIR}" "$@"

find "${OUTDIR}" -maxdepth 2 -print || true
