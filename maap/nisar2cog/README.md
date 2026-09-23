# rift `nisar2cog` — MAAP OGC application package

Runs the rift `nisar2cog` workflow on MAAP DPS: a NISAR L2 **GSLC** granule →
per-polarization amplitude (and phase) COGs on the Antarctica master grid (EPSG:3031),
lossless placement, no inference.

This package follows MAAP's [`NISAR_DPS_JOB`](https://github.com/MAAP-Project/NISAR_DPS_JOB)
reference pattern: the algorithm is built on MAAP's **`maap_base`** image with a
`build_command` (conda env) + `run_command`, and the **worker downloads the granule itself**
using MAAP/ASF temporary credentials. `nisar2cog` needs **no ISCE3**, so the conda env stays
light (numpy/scipy/h5py/rasterio/gdal/pyproj + s3fs/earthaccess/maap-py) and avoids the
isce3/gdal conda-solve issues in NASA-IMPACT/science-support#81.

## Why `maap_base` (not a slim GHCR image)

The credentialed S3 fetch relies on `maap.aws.earthdata_s3_credentials(...)`, which needs
maap-py **and** the DPS credential plumbing that ships in `maap_base`. That base image lives
in the private `mas.maap-project.org` registry, which only MAAP's build infra can pull — so
the image is built on MAAP's side (via the Algorithm Catalog / `build_command`), not on
GitHub Actions.

## Files

| File | Role |
|------|------|
| `algorithm_config.yml` | OGC algorithm description: `base_container_url`, `build_command`, `run_command`, named inputs/outputs, resource hints |
| `build.sh` | Build step: creates the `rift_nisar2cog` conda env from `env.yml` and installs rift |
| `env.yml` | Conda env (rift deps + s3fs/earthaccess/maap-py; no isce3) |
| `run.sh` | Run step: `mkdir output`, activates the env, calls `nisar2cog_dps.py` |
| `nisar2cog_dps.py` | Resolves + downloads the granule (S3 temp creds / CMR / auth HTTPS), then runs `rift nisar2cog` |
| `Dockerfile` | `FROM maap_base`; copies the repo, sets `run.sh` as entrypoint |
| `nisar2cog.cwl` | Reference CWL for local `cwltool` runs |

Inputs (all named):
- `access_mode` — `auto` (S3 first, HTTPS fallback) | `s3` | `https`.
- `s3_href` / `https_href` — direct granule URL. If both blank, resolved via CMR.
- `short_name` (`NISAR_L2_GSLC_PROVISIONAL_V1`) / `granule_index` — CMR search fallback.
- `asf_s3_creds_url` — ASF temporary-S3-credentials endpoint.
- `pols` — comma-separated (`HH,HV`); empty = all freq-A pols.
- `amp_only` — `true|false`; `true` skips phase COGs.

Output: `output/` directory (staged out to `~/my-private-bucket/dps_output/rift-nisar2cog/...`).

## Stage 1 — local pre-flight (MAAP Hub terminal, no DPS)

Run in an OGC Hub workspace (maap-py v5, Earthdata login available):

```bash
cd ~ && git clone https://github.com/nemo794/rift.git && cd rift
pip install . earthaccess s3fs

# Discover + download one granule (authenticated), then run the DPS entrypoint the way
# the worker will (S3-preferred). This exercises fetch + rift nisar2cog end-to-end.
python maap/nisar2cog/nisar2cog_dps.py \
    --access_mode auto \
    --short_name NISAR_L2_GSLC_PROVISIONAL_V1 \
    --granule_index 0 \
    --pols "" --amp_only false \
    --out_dir output
ls -la output/                                   # <pol>_amplitude.tif (+ <pol>_phase.tif)
gdalinfo output/*amplitude.tif | grep -E "EPSG|Size"   # expect EPSG:3031
```

Or test just the science step against a granule you've already downloaded:
```bash
rift nisar2cog --gslc /path/to/NISAR_..._GSLC_....h5 --output output/
```

## Stage 2 — register + run on DPS

Registration builds the image on MAAP's side (it can pull `maap_base`):

1. In the MAAP Hub: **Launcher → Algorithm Catalog → Register New Algorithm**, and load
   `maap/nisar2cog/algorithm_config.yml` (or fill the form to match it). This uses
   `build_command: rift/maap/nisar2cog/build.sh` on `base_container_url: maap_base:v5.0.0`.
   Watch the Build & Deployment UI until the process is built/deployed.
2. Confirm with `maap.list_algorithms()` (look for `rift-nisar2cog`), then submit jobs from
   `notebooks/nisar2cog_dps_runner.ipynb`. The algorithm needs 16 GB / 4 CPU
   (`ram_min: 16`, `cores_min: 4`), so submit to **`maap-dps-worker-16gb`** — the
   `maap-dps-sandbox` queue (8 GB) is too small. Use `maap-dps-worker-32gb` for large granules.

### Granule access on the worker
The worker pulls NISAR from ASF directly — **no pre-staging to a bucket needed**. In `auto`
mode it fetches from `s3://sds-n-cumulus-prod-nisar-products/...` using ASF temporary S3
credentials (`maap.aws.earthdata_s3_credentials`), falling back to authenticated HTTPS via
`earthaccess`. Submit an `s3_href` (preferred) or `https_href`, or let it resolve by
`short_name` + `granule_index`.
