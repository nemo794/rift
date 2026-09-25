# rift `biomass-e2e` — MAAP OGC application package

Runs the full BIOMASS crevasse-detection pipeline on MAAP DPS:

1. **Geocode** — an ESA BIOMASS Level-1A **SCS** granule → per-polarization amplitude (and
   phase) COGs on the Antarctica master grid (EPSG:3031, 5×5 m, 512×512 chunks), geocoded
   with ISCE3 (`rift biomass2cog`). All four pols HH,HV,VH,VV are geocoded.
2. **Intensity** — square each `*_<POL>_amp.tif` into a co-registered `*_<POL>_intensity.tif`
   (`scripts/make_pwr_cogs.py`). These four intensity COGs are the inputs the crevasse model
   consumes.
3. **Inference** — the **nisar-crevasse** BIOMASS gate + U-Net model runs on the directory of
   intensity COGs, writing `gate_prob.tif` + `unet_prob.tif` into the same `output/`.

All steps run behind one entrypoint, each in its own conda env. This package extends the
[`biomass2cog`](../biomass2cog/README.md) package with the ML inference step (the way
[`nisar-e2e`](../nisar_e2e/README.md) extends `nisar2cog`), so it follows the same MAAP
`maap_base` + `build_command` + `run_command` pattern. Because BIOMASS is **ESA** data (not
on ASF S3), the worker authenticates to ESA with an **access token** and streams the product
zip **inside the algorithm** — see the `biomass2cog` README for the full data-access story.

## Why all four polarizations, and why `*_intensity.tif`

The BIOMASS U-Net is a **4-channel** model (HH,HV,VH,VV), and the crevasse reader
(`nisar-crevasse`'s `crevasse.biomass.run_granule._granule_paths`) globs
`*_<POL>_intensity.tif` for **each** of the four pols — a missing pol is a hard error. So:

- The pols are **hardcoded** to `HH,HV,VH,VV` in `biomass_e2e_dps.py` (not a job input).
- `scripts/make_pwr_cogs.py` writes `*_<POL>_intensity.tif` (linear intensity = amplitude²).
  The suffix is a hard contract with the reader, not cosmetic. (This shared script is also
  used by the `biomass2cog` package, which now emits the same `*_intensity.tif`.)

## Two conda envs in one image

`build.sh` creates both at registration time:

| Env | Role |
|-----|------|
| `rift_biomass2cog` | Heavy isce3/gdal geocoding env — `rift biomass2cog` + biomass-reader (from GitHub) + sardem (DEM auto-download) + the ESA-access deps (requests / pystac-client / maap-py) + boto3 (for the model fetch). |
| `crevasse` | The [`nisar-crevasse`](https://github.com/nemo794/nisar-crevasse) BIOMASS gate + U-Net inference env (Python 3.11, torch, safetensors, scikit-image/-learn, rasterio). |

`run.sh` starts the entrypoint in `rift_biomass2cog`; the entrypoint shells out to `crevasse`
via `conda run -n crevasse` for the inference step.

### Baked model

The large BIOMASS U-Net checkpoint (`unet_best.safetensors`, ~199 MB) exceeds GitHub's 100 MB
limit and is **not** in the `nisar-crevasse` repo. `my-public-bucket` is **not** anonymously
readable over HTTPS (it returns 403), so `build.sh` fetches the model with **boto3 using
credentials** — MAAP workspace credentials (`maap.aws.workspace_bucket_credentials()`) first,
then the default AWS credential chain. The fetch runs **right after the geocoding env is
built** (that env supplies boto3 + maap-py) and **before** the heavy crevasse solve and the
clone — fail early, staging to a temp file. The model is copied into the clone once it exists,
at the exact nested path the BIOMASS predictor loads by default (`bio_unet_predict.py`'s
`DEFAULT_CHECKPOINT` — the **biomass**-specific directory, not the nisar one):

```
<clone>/models/biomass/unet/bio_unet_4ch_frangi_aux_nw0p02/unet_best.safetensors
```

Override the source with the `MODEL_S3_URI` env var; the default is
`s3://maap-ops-workspace/shared/niemoell/crevasse_unet_models/biomass/unet_best.safetensors`.
The build **hard-fails** if the model is missing or empty after the fetch (and the crevasse
sanity check re-asserts it loads). The RF gate (`bio_gate_t512.joblib`, ~13 MB) and the
checkpoint's `.json` sidecar ship in the repo, so only the one safetensors file is fetched.
The default gate method is `rf`, which needs no CNN weights.

## Files

| File | Role |
|------|------|
| `algorithm_config.yml` | OGC algorithm description: `base_container_url`, `build_command`, `run_command`, named inputs/outputs, resource hints |
| `build.sh` | Build step: creates both conda envs, installs rift + biomass-reader + nisar-crevasse, bakes the BIOMASS U-Net model |
| `env.yml` | Geocoding conda env (`rift_biomass2cog`; isce3 + biomass-reader stack + boto3) |
| `run.sh` | Run step: `mkdir output`, activates the geocoding env, calls `biomass_e2e_dps.py` |
| `biomass_e2e_dps.py` | Resolves the Item on the ESA STAC, exchanges ESA creds for a token, streams the product zip, runs `rift biomass2cog`, derives `*_intensity.tif`, then `crevasse-export-geotiff biomass` |
| `Dockerfile` | `FROM maap_base`; copies the repo, sets `run.sh` as entrypoint |
| `biomass_e2e.cwl` | Reference CWL for local `cwltool` runs |

Inputs (all named):
- `item_id` — ESA BIOMASS L1A SCS STAC Item ID (collection `BiomassLevel1a`), e.g.
  `BIO_S1_SCS__1S_20260922T230451_..._DY7A91`.
- `amp_only` — `true|false`; `true` skips the per-pol *phase* COGs (amplitude + intensity are
  still written — intensity is required for inference).
- `max_tiles` — cap on candidate tiles for inference (prefix of the scan order, for a quick
  check). Empty = full granule (slow on CPU).
- `crop_to_scanned` — `true|false`; crop the inference GeoTIFFs to the scanned bounding box
  (pair with `max_tiles` so a capped run is not a mostly-NaN full-granule raster). Mutually
  exclusive with `edge_margin`.
- `gate_thresh` — gate probability threshold for flagging tiles (default `0.65`).
- `edge_margin` — overlap-stride rescoring to remove the tile-seam artifact (`0` = off, more
  compute). Mutually exclusive with `crop_to_scanned`.

The 5×5 m master grid, the DEM auto-download (via sardem), and the four polarizations are
fixed (not job inputs).

Output: `output/` directory (staged out to `~/my-private-bucket/dps_output/rift-biomass-e2e/...`),
containing the amplitude/phase/intensity COGs **and** `gate_prob.tif` + `unet_prob.tif`.

## Prerequisite — register credentials as MAAP secrets

The worker needs two sets of credentials, both a one-time setup (from any MAAP Hub Python
session). This mirrors the `biomass2cog` package.

1. **ESA credentials** (to fetch the BIOMASS granule). Follow the MAAP docs,
   [ESA BIOMASS Data Access](https://docs.maap-project.org/en/latest/science/ESA_BIOMASS/ESA_BIOMASS_Data_Access.html),
   to get an ESA-MAAP **client secret** and an **offline (refresh) token**, then:
   ```python
   from maap.maap import MAAP
   maap = MAAP()
   maap.secrets.add_secret("ESA_MAAP_CLIENT_SECRET", "<client-secret>")
   maap.secrets.add_secret("ESA_OFFLINE_TOKEN", "<offline-token>")
   ```
2. **NASA Earthdata credentials** (for the sardem DEM download, which pulls from the NISAR
   DEM store behind Earthdata Login — a NASA account, separate from ESA):
   ```python
   maap.secrets.add_secret("EARTHDATA_USERNAME", "<username>")
   maap.secrets.add_secret("EARTHDATA_PASSWORD", "<password>")
   ```
   Sign up free at https://urs.earthdata.nasa.gov/users/new.

**Local testing** uses env vars instead of MAAP secrets — the entrypoint checks the
environment first:
```bash
export ESA_MAAP_CLIENT_SECRET=... ESA_OFFLINE_TOKEN=...
export EARTHDATA_USERNAME=... EARTHDATA_PASSWORD=...
```

## Stage 1 — local pre-flight (MAAP Hub terminal, no DPS)

Run in an OGC Hub workspace. Build both envs + fetch the model exactly as DPS registration
does:

```bash
cd ~ && git clone -b maap-ogc-biomass-e2e https://github.com/nemo794/rift.git && cd rift
bash maap/biomass_e2e/build.sh

export ESA_MAAP_CLIENT_SECRET=... ESA_OFFLINE_TOKEN=...
export EARTHDATA_USERNAME=... EARTHDATA_PASSWORD=...

# Run the DPS entrypoint the way the worker will, capped for a quick check:
conda run --live-stream -p /opt/conda/envs/rift_biomass2cog \
  python maap/biomass_e2e/biomass_e2e_dps.py \
    --item_id BIO_S1_SCS__1S_..._DY7A91 \
    --amp_only false \
    --max_tiles 100 --crop_to_scanned true \
    --out_dir output
ls -la output/    # *_{HH,HV,VH,VV}_amp.tif (+ _phs.tif) + *_intensity.tif, gate_prob.tif, unet_prob.tif
```

Test just the inference half against a directory of intensity COGs you already have:
```bash
conda run -n crevasse crevasse-export-geotiff biomass \
    --granule output/ --out-dir output --max-tiles 100 --crop-to-scanned
```

## Stage 2 — register + run on DPS

Registration builds the image on MAAP's side (it can pull `maap_base`):

1. In the MAAP Hub: **Launcher → Algorithm Catalog → Register New Algorithm**, and load
   `maap/biomass_e2e/algorithm_config.yml` (or fill the form to match it). This uses
   `build_command: rift/maap/biomass_e2e/build.sh` on `base_container_url: maap_base:v5.0.0`,
   and registers from the **`maap-ogc-biomass-e2e`** branch (`algorithm_version`). The isce3
   geocoding env, the crevasse torch env, and the ~199 MB model fetch make this a longer build
   than either `biomass2cog` or `nisar-e2e` — watch the Build & Deployment UI for conda-solve
   issues (see NASA-IMPACT/science-support#81).
2. Confirm with `maap.list_algorithms()` (look for `rift-biomass-e2e`), then submit jobs from
   `notebooks/biomass_e2e_dps_runner.ipynb`. Test the plumbing on **`maap-dps-sandbox`** with a
   single Item and `max_tiles=100` (the algorithm declares 32 GB / 8 CPU, which exceeds
   sandbox's 8 GB / 10-min cap, so a full granule will OOM or time out there — it only proves
   the job is accepted). For real runs submit to **`maap-dps-worker-32gb`**; expect a
   full-granule U-Net run to take tens of minutes to hours on CPU.

### Granule access on the worker
The worker resolves the `item_id` on the ESA MAAP STAC
(`https://catalog.maap.eo.esa.int/catalogue/`), exchanges the ESA offline token for an access
token at the ESA IAM endpoint, and streams the full product zip (the `product` asset, served
from `/data/zipper/...`) with an `Authorization: Bearer` header. No pre-staging to a bucket,
and no ASF/Earthdata credentials are involved for the granule (Earthdata is only for the DEM).
