# rift `nisar2cog` — MAAP OGC application package

Runs the rift `nisar2cog` workflow on MAAP DPS: a NISAR L2 **GSLC** granule →
per-polarization amplitude (and phase) COGs on the Antarctica master grid (EPSG:3031),
lossless placement, no inference.

This is the **OGC** app-package path (maap-py ≥ v5), not the classic HySDS registration.
`nisar2cog` needs no ISCE3 — the image is a slim `python:3.12-slim` with rift + its
numpy/scipy/h5py/rasterio/pyproj wheels, so it avoids the isce3/gdal conda-solve issues in
NASA-IMPACT/science-support#81.

## Files

| File | Role |
|------|------|
| `algorithm_config.yml` | OGC algorithm description (named inputs/outputs, resource hints) |
| `Dockerfile` | Slim image; installs rift + `requests`; puts `run.py` on PATH |
| `run.py` | Entrypoint: downloads `--gslc_url` into `input/`, runs `rift nisar2cog`, writes `output/` |
| `requirements.txt` | Convenience deps for the local pre-flight test |
| `input.yml` | Sample `cwltool` job file |

Inputs (all named — OGC has no positional args):
- `gslc_url` — HTTPS/S3 URL to a NISAR L2 GSLC `.h5` (downloaded at runtime).
- `pols` — comma-separated (`HH,HV`); empty = all freq-A pols.
- `amp_only` — `true|false`; `true` skips phase COGs.

Output: `output/` directory (staged out to `~/my-private-bucket/dps_output/rift-nisar2cog/...`).

## Stage 1 — local pre-flight (MAAP Hub terminal, no DPS)

```bash
# 1. Get the code and install into the current Python (no conda needed).
cd ~ && git clone https://github.com/nemo794/rift.git && cd rift
pip install . requests

# 2. Make a scratch dir that mimics the DPS layout.
mkdir -p run_test/input run_test/output && cd run_test

# 3a. Raw CLI check — stage a granule by hand into input/ first
#     (earthaccess.download(results[:1], "input") after earthaccess.login(),
#      or `aws s3 cp s3://.../NISAR_..._GSLC_....h5 input/`).
rift nisar2cog --gslc input/<granule>.h5 --output output/
ls -la output/                      # expect <pol>_amplitude.tif (+ <pol>_phase.tif)
gdalinfo output/*.tif | grep -E "EPSG|Size|Pixel"   # confirm EPSG:3031

# 3b. Exercise the OGC entrypoint end-to-end (downloads the granule itself).
cd ~/rift && python maap/nisar2cog/run.py --gslc_url <https-url> --pols "" --amp_only false
ls -la output/
```

Optional CWL parity check (what DPS actually runs):
```bash
git clone https://github.com/MAAP-Project/ogc-app-pack-generator.git
pip install cwltool ogc_ap_validator
python ogc-app-pack-generator/build_cwl_workflow.py \
    --config-file maap/nisar2cog/algorithm_config.yml     # -> cwl_workflows/process.cwl
cwltool --validate cwl_workflows/process.cwl
ap-validator cwl_workflows/process.cwl
# Full local run (edit input.yml with a reachable gslc_url first):
cwltool cwl_workflows/process.cwl maap/nisar2cog/input.yml
```

## Stage 2 — deploy + run on DPS

1. Add a repo secret `MAAP_TOKEN` (from https://console.maap-project.org/profile/tokens).
2. Push this branch. `.github/workflows/ogc-app-pack.yml` generates + validates the CWL,
   builds and pushes `ghcr.io/nemo794/rift-nisar2cog:main`, and registers the process.
3. Confirm registration and submit jobs from `notebooks/nisar2cog_dps_runner.ipynb`
   (bounding-box search → submit loop → status/results). Start on the **`maap-dps-sandbox`**
   queue (8 GB, 10-min cap) with a single granule, then scale up. If sandbox limits are hit,
   resubmit with `queue="maap-dps-worker-16gb"` (or `-32gb`).

### Note on granule access
ASF NISAR data typically requires Earthdata Login. If a `gslc_url` is not anonymously
downloadable on a DPS worker, either (a) stage the granule to your MAAP bucket and pass that
URL, or (b) add Earthdata credentials (`~/.netrc`) to the image / run step. Verify with a
single sandbox job before scaling the loop.
