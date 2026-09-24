# rift `nisar-e2e` — MAAP OGC application package

Runs the full NISAR crevasse-detection pipeline on MAAP DPS:

1. **Geocode** — a NISAR L2 **GSLC** granule → per-polarization amplitude (and phase) COGs
   on the Antarctica master grid (EPSG:3031), lossless placement (`rift nisar2cog`).
2. **Inference** — the **nisar-crevasse** gate + U-Net model runs on the HH amplitude COG,
   writing `gate_prob.tif` + `unet_prob.tif` into the same `output/`.

Both steps run behind one entrypoint, each in its own conda env. This package extends the
[`nisar2cog`](../nisar2cog/README.md) package with the ML inference step, so it follows the
same MAAP `maap_base` + `build_command` + `run_command` pattern (the worker downloads the
granule itself using MAAP/ASF temporary credentials).

## Two conda envs in one image

`build.sh` creates both at registration time:

| Env | Role |
|-----|------|
| `rift_nisar2cog` | Slim geocoding env (rift + numpy/scipy/h5py/rasterio/gdal/pyproj + s3fs/earthaccess/maap-py). No isce3 — avoids the isce3/gdal conda-solve issues in NASA-IMPACT/science-support#81. |
| `crevasse` | The [`nisar-crevasse`](https://github.com/nemo794/nisar-crevasse) gate + U-Net inference env (Python 3.11, torch 2.5.1, safetensors, scikit-image/-learn, rasterio). |

`run.sh` starts the entrypoint in `rift_nisar2cog`; the entrypoint shells out to `crevasse`
via `conda run -n crevasse` for the inference step.

### Baked model

The large NISAR U-Net checkpoint (`unet_best.safetensors`, ~153 MB) exceeds GitHub's 100 MB
limit and is **not** in the `nisar-crevasse` repo. `my-public-bucket` is **not** anonymously
readable over HTTPS (it returns 403), so `build.sh` fetches the model with **boto3 using
credentials** — MAAP workspace credentials (`maap.aws.workspace_bucket_credentials()`, always
present on `maap_base`) first, then the default AWS credential chain — and places it at the
exact nested path the predictor loads by default:

```
<clone>/models/nisar/unet/unet_025_019_f421_meansoft_g3/unet_best.safetensors
```

Override the source with the `MODEL_S3_URI` env var; the default is
`s3://maap-ops-workspace/shared/niemoell/crevasse_unet_models/nisar/unet_best.safetensors`.
The build **hard-fails** if the model is missing or empty after the fetch (and the crevasse
sanity check re-asserts it loads), so a broken download can no longer pass as a successful
build. The gate model (`gate_5m_freqA_2gran.joblib`, <100 MB) and the checkpoint's `.json`
sidecar ship in the repo, so only the one safetensors file is fetched.

## Files

| File | Role |
|------|------|
| `algorithm_config.yml` | OGC algorithm description: `base_container_url`, `build_command`, `run_command`, named inputs/outputs, resource hints |
| `build.sh` | Build step: creates both conda envs, installs rift + nisar-crevasse, bakes the U-Net model |
| `env.yml` | Geocoding conda env (`rift_nisar2cog`; no isce3) |
| `run.sh` | Run step: `mkdir output`, activates the geocoding env, calls `nisar_e2e_dps.py` |
| `nisar_e2e_dps.py` | Resolves + downloads the granule, runs `rift nisar2cog`, then `crevasse-export-geotiff nisar` |
| `Dockerfile` | `FROM maap_base`; copies the repo, sets `run.sh` as entrypoint |
| `nisar_e2e.cwl` | Reference CWL for local `cwltool` runs |

Inputs (all named):
- `access_mode` — `auto` (S3 first, HTTPS fallback) | `s3` | `https`.
- `s3_href` / `https_href` — direct granule URL. If both blank, resolved via CMR.
- `short_name` (`NISAR_L2_GSLC_PROVISIONAL_V1`) / `granule_index` — CMR search fallback.
- `asf_s3_creds_url` — ASF temporary-S3-credentials endpoint.
- `pols` — comma-separated (`HH,HV`); empty = all freq-A pols.
- `amp_only` — `true|false`; `true` skips phase COGs.
- `max_tiles` — cap on candidate tiles for inference (prefix of the swath scan order, for a
  quick check). Empty = full swath (slow on CPU).
- `crop_to_scanned` — `true|false`; crop the inference GeoTIFFs to the scanned bounding box
  (pair with `max_tiles` so a capped run is not a mostly-NaN full-swath raster).

Output: `output/` directory (staged out to `~/my-private-bucket/dps_output/rift-nisar-e2e/...`),
containing the amplitude/phase COGs **and** `gate_prob.tif` + `unet_prob.tif`.

## Stage 1 — local pre-flight (MAAP Hub terminal, no DPS)

Run in an OGC Hub workspace (maap-py v5, Earthdata login available):

```bash
cd ~ && git clone https://github.com/nemo794/rift.git && cd rift
# Build both envs + fetch the model exactly as DPS registration does:
bash maap/nisar_e2e/build.sh

# Run the DPS entrypoint the way the worker will (S3-preferred), capped for a quick check:
conda run --live-stream -p /opt/conda/envs/rift_nisar2cog \
  python maap/nisar_e2e/nisar_e2e_dps.py \
    --access_mode auto \
    --short_name NISAR_L2_GSLC_PROVISIONAL_V1 --granule_index 0 \
    --pols "" --amp_only false \
    --max_tiles 100 --crop_to_scanned true \
    --out_dir output
ls -la output/                    # *_HH_amp.tif (+ *_phs.tif), gate_prob.tif, unet_prob.tif
```

Or test just the inference half against an amplitude COG you already have:
```bash
conda run -n crevasse crevasse-export-geotiff nisar \
    --granule output/NISAR_..._HH_amp.tif --out-dir output --max-tiles 100 --crop-to-scanned
```

## Stage 2 — register + run on DPS

Registration builds the image on MAAP's side (it can pull `maap_base`):

1. In the MAAP Hub: **Launcher → Algorithm Catalog → Register New Algorithm**, and load
   `maap/nisar_e2e/algorithm_config.yml` (or fill the form to match it). This uses
   `build_command: rift/maap/nisar_e2e/build.sh` on `base_container_url: maap_base:v5.0.0`.
   Watch the Build & Deployment UI until the process is built/deployed (this build clones
   nisar-crevasse, solves the `crevasse` env, and fetches the model — expect it to take
   longer than `nisar2cog`).
2. Confirm with `maap.list_algorithms()` (look for `rift-nisar-e2e`), then submit jobs from
   `notebooks/nisar_e2e_dps_runner.ipynb`. Test the plumbing on **`maap-dps-sandbox`** with a
   single granule and `max_tiles=100` (the U-Net is CPU-bound; a full swath would blow the
   sandbox's 10-min cap). For real runs submit to **`maap-dps-worker-16gb`** (or `-32gb`),
   and expect a full-swath run to take tens of minutes to hours on CPU.

### Granule access on the worker
The worker pulls NISAR from ASF directly — **no pre-staging to a bucket needed**. In `auto`
mode it fetches from `s3://sds-n-cumulus-prod-nisar-products/...` using ASF temporary S3
credentials (`maap.aws.earthdata_s3_credentials`), falling back to authenticated HTTPS via
`earthaccess`. Submit an `s3_href` (preferred) or `https_href`, or let it resolve by
`short_name` + `granule_index`.
