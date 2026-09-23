# rift `biomass2cog` — MAAP OGC application package

Runs the rift `biomass2cog` workflow on MAAP DPS: an ESA BIOMASS Level-1A **SCS**
granule → per-polarization amplitude (and phase) COGs on the Antarctica master grid
(EPSG:3031, 5×5 m, 512×512 chunks), geocoded with ISCE3. No inference.

This package mirrors the `maap/nisar2cog/` package, but the data-access story is
different. BIOMASS is **ESA** data, not on ASF S3, so — following MAAP's ESA BIOMASS
guidance and the [`MAAP-Project/esa-biomass-gamma0`](https://github.com/MAAP-Project/esa-biomass-gamma0)
reference — the worker authenticates to ESA with an **access token** and streams the
product **inside the algorithm** (egress happens at read time, not via maap-py input
staging). The conda env is the heavy isce3/biomass stack (isce3 + gdal + biomass-reader
+ sardem), not the light NISAR env.

## Why `maap_base`

`MAAP().secrets.get_secret(...)` (used to read the ESA credentials on the worker) needs
maap-py **and** the DPS credential plumbing that ships in `maap_base`. That base image
lives in the private `mas.maap-project.org` registry, which only MAAP's build infra can
pull — so the image is built on MAAP's side (via the Algorithm Catalog / `build_command`),
not on GitHub Actions.

## Files

| File | Role |
|------|------|
| `algorithm_config.yml` | OGC algorithm description: `base_container_url`, `build_command`, `run_command`, named inputs/outputs, resource hints |
| `build.sh` | Build step: creates the `rift_biomass2cog` conda env, clones + installs biomass-reader, installs rift |
| `env.yml` | Conda env (isce3 + gdal + biomass-reader stack + obstore/pystac-client/maap-py) |
| `run.sh` | Run step: `mkdir output`, activates the env, calls `biomass2cog_dps.py` |
| `biomass2cog_dps.py` | Resolves the Item on the ESA STAC, exchanges ESA creds for a token, streams the product zip, then runs `rift biomass2cog` |
| `Dockerfile` | `FROM maap_base`; copies the repo, sets `run.sh` as entrypoint |
| `biomass2cog.cwl` | Reference CWL for local `cwltool` runs |

Inputs (all named):
- `item_id` — ESA BIOMASS L1A SCS STAC Item ID (collection `BiomassLevel1a`), e.g.
  `BIO_S1_SCS__1S_20260922T230451_..._DY7A91`.
- `pols` — comma-separated (default `HH,HV,VH,VV`).
- `amp_only` — `true|false`; `true` skips phase COGs.

The 5×5 m master grid and DEM auto-download (via sardem) are fixed (not job inputs).

Output: `output/` directory (staged out to `~/my-private-bucket/dps_output/rift-biomass2cog/...`).

## Prerequisite — register ESA credentials as MAAP secrets

The worker needs an ESA long-lasting (offline) token. This is a one-time setup.

1. **Obtain the token.** Follow the MAAP docs,
   [ESA BIOMASS Data Access](https://docs.maap-project.org/en/latest/science/ESA_BIOMASS/ESA_BIOMASS_Data_Access.html),
   to get an ESA-MAAP **client secret** and an **offline (refresh) token**.
2. **Register both as MAAP secrets** (once, from any MAAP Hub Python session):
   ```python
   from maap.maap import MAAP
   maap = MAAP()
   maap.secrets.add_secret("ESA_MAAP_CLIENT_SECRET", "<client-secret>")
   maap.secrets.add_secret("ESA_OFFLINE_TOKEN", "<offline-token>")
   maap.secrets.get_secrets()   # confirm both names are present
   ```
   (Or use the MAAP secrets UI.) The DPS worker reads them with
   `MAAP().secrets.get_secret("ESA_MAAP_CLIENT_SECRET" | "ESA_OFFLINE_TOKEN")`.
3. **Local testing** uses env vars instead of MAAP secrets — the entrypoint checks the
   environment first:
   ```bash
   export ESA_MAAP_CLIENT_SECRET=...
   export ESA_OFFLINE_TOKEN=...
   ```

## Stage 1 — local pre-flight (MAAP Hub terminal, no DPS)

Run in an OGC Hub workspace in the `rift` conda env (isce3 + biomass-reader installed):

```bash
cd ~ && git clone -b maap-ogc-biomass2cog https://github.com/nemo794/rift.git && cd rift
export ESA_MAAP_CLIENT_SECRET=... ESA_OFFLINE_TOKEN=...

# Resolve + download one granule (authenticated), then run the DPS entrypoint the way
# the worker will. This exercises the ESA fetch + rift biomass2cog end-to-end.
python maap/biomass2cog/biomass2cog_dps.py \
    --item_id BIO_S1_SCS__1S_..._DY7A91 \
    --pols "HH,HV,VH,VV" --amp_only false \
    --out_dir output
ls -la output/                                     # <granule>_<POL>_amp.tif (+ _phs.tif)
gdalinfo output/**/*_amp.tif | grep -E "EPSG|Size" # expect EPSG:3031
```

Or test just the science step against a granule you've already downloaded:
```bash
rift biomass2cog --granule /path/to/BIO_..._SCS_....zip --output output/ --pols "[HH,HV,VH,VV]"
```

## Stage 2 — register + run on DPS

Registration builds the image on MAAP's side (it can pull `maap_base`):

1. In the MAAP Hub: **Launcher → Algorithm Catalog → Register New Algorithm**, and load
   `maap/biomass2cog/algorithm_config.yml` (or fill the form to match it). This uses
   `build_command: rift/maap/biomass2cog/build.sh` on `base_container_url: maap_base:v5.0.0`,
   and registers from the **`maap-ogc-biomass2cog`** branch (`algorithm_version`). The
   isce3/gdal/biomass-reader env is heavy — expect a longer build than nisar2cog, and watch
   the Build & Deployment UI for conda-solve issues (see NASA-IMPACT/science-support#81; the
   fallback is the isce3 image wildintellect built).
2. Confirm with `maap.list_algorithms()` (look for `rift-biomass2cog`), then submit jobs from
   `notebooks/biomass2cog_dps_runner.ipynb`. Test the plumbing on **`maap-dps-sandbox`** with
   a single Item. The algorithm declares 32 GB / 8 CPU / 50 GB out — which exceeds sandbox's
   8 GB / 10-min cap, so a full granule may OOM or time out there. For real runs submit to
   **`maap-dps-worker-32gb`**.

### Granule access on the worker
The worker resolves the `item_id` on the ESA MAAP STAC
(`https://catalog.maap.eo.esa.int/catalogue/`), exchanges the ESA offline token for an
access token at the ESA IAM endpoint, and streams the full product zip (the `product`
asset, served from `/data/zipper/...`) with an `Authorization: Bearer` header via
`obstore`. No pre-staging to a bucket, and no ASF/Earthdata credentials are involved.
