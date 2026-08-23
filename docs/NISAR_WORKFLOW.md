# NISAR Workflow — Algorithm

Extracts frequency-A amplitude from a NISAR L2 GSLC granule and regrids it onto the
master grid, writing an amplitude-only Cloud-Optimized GeoTIFF per polarization.

## Input

- NISAR L2 GSLC HDF5 (`NISAR_L2_PR_GSLC_*.h5`)
- Polarization(s): default all available in **frequency A** (HH, HV, VV, VH)
- Grid spacing (default **5×5 m**; `--native` → **5×5 m**, snap only), resampling method

**Frequency A only.** Frequency B is intentionally ignored even when present.

## Output

- One amplitude COG per polarization: `<granule>_<POL>_amp.tif`
  - Band 1: linear amplitude (`float32`), `NaN` = invalid/no-data
  - 512×512 tiling, DEFLATE + predictor 3, aligned to master-grid chunk boundaries

## Key facts about NISAR GSLC

- Already projected to **EPSG:3031** at **5×5 m** posting → this is a *resample + snap*,
  **not** a CRS reprojection.
- Chunked 512×512 in the HDF5 → natural tile size for streaming.
- Masks:
  - `frequencyA/mask`: 0 = invalid, ≥1 = valid.
  - `frequencyA/inputDataExceptionMask`: applied **only to HV**, ≥1 = invalid.

## Algorithm

### 1. Read geometry & polarizations (`nisar/extract.py`)

- Read `frequencyA/{projection, xCoordinates, yCoordinates, xCoordinateSpacing,
  yCoordinateSpacing, listOfPolarizations}`.
- Build the native affine transform (shift coordinates by half a pixel: HDF5 stores pixel
  centers, GDAL expects the corner).

### 2. Regrid in the complex domain (`nisar/regrid.py`)

This is where the two signal-processing rules from
[GRID_RESAMPLING_DECISION.md](GRID_RESAMPLING_DECISION.md) live.

1. Compute the target geogrid: snap the granule's native extent to master-grid chunk
   boundaries via `grid.snap_bbox(expand=True)` at the target spacing.
2. Resample the **complex** GSLC (not detected amplitude) from native 5×5 to target
   spacing:
   - **Default 5×5:** no spacing change; only an origin/lattice shift so pixel edges land
     on master-grid lines (sub-pixel complex interpolation → true chunk co-registration).
   - **Downsampled axis** (e.g. 5→40 range if a coarser grid is chosen): apply an explicit
     **anti-alias low-pass** (block-average / Lanczos) *before* decimation. The
     resampling-method parameter selects the kernel but never bypasses anti-aliasing on a
     downsampling path.
3. **Detect last:** `amplitude = |resampled complex|`. Amplitude is never resampled
   directly, because `|·|` doubles bandwidth and would alias / corrupt speckle statistics.

### 3. Apply masks & write COG (`nisar/extract.py`)

- Apply `frequencyA/mask` (0 → NaN) to every polarization.
- Apply `inputDataExceptionMask` (≥1 → NaN) to **HV only**.
- Stream in 512×512 tiles for memory efficiency (files can be 100+ GB), write a temporary
  tiled GeoTIFF, then `gdal_translate -of COG` (512 blocksize, DEFLATE/ZLEVEL=1/PREDICTOR=3,
  BIGTIFF=YES, AVERAGE overviews).

## `--native` mode

Keeps 5×5 posting and snaps the extent to chunk boundaries (fill margin may expand to reach
a whole number of chunks). Aligns with other NISAR products, but not necessarily with
BIOMASS unless the master grid is also 5×5.
