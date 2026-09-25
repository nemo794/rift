#!/usr/bin/env bash
################################################################################
# MAAP DPS run script for the rift biomass2cog OGC algorithm.
#
# DPS passes the registered inputs as --name value pairs. This wrapper creates the
# output/ directory and hands off to the Python entrypoint inside the conda env.
################################################################################
set -euo pipefail

basedir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
OUTDIR="${USER_OUTPUT_DIR:-${OUTPUT_DIR:-output}}"
mkdir -p "${OUTDIR}"

conda run --live-stream -p /opt/conda/envs/rift_biomass2cog \
  python "${basedir}/biomass2cog_dps.py" --out_dir "${OUTDIR}" "$@"

# Derive per-polarization intensity (power) COGs from the *_amp.tif COGs that
# biomass2cog just wrote, alongside them in the output directory (as *_intensity.tif).
# Best-effort: a failure here (e.g. no amp COGs on an amp-only=false run) must not fail
# the job.
conda run --live-stream -p /opt/conda/envs/rift_biomass2cog \
  python "${basedir}/../../scripts/make_pwr_cogs.py" "${OUTDIR}" --output-dir "${OUTDIR}" \
  || echo "WARNING: make_pwr_cogs.py failed; continuing without intensity COGs" >&2

find "${OUTDIR}" -maxdepth 2 -print || true
