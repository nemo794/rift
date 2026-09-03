# NISAR Workflow — Algorithm

Extracts frequency-A amplitude from a NISAR L2 GSLC granule and places it onto the master
grid, writing a Cloud-Optimized GeoTIFF per polarization. Placement is **lossless**: there
is no resampling, no interpolation, and no subpixel shift.

## Input

- NISAR L2 GSLC HDF5 (`NISAR_L2_PR_GSLC_*.h5`)
- Polarization(s): default all available in **frequency A** (HH, HV, VV, VH)

**Frequency A only.** Frequency B is intentionally ignored even when present.

The master grid is fixed at **5×5 m** (shared with BIOMASS). NISAR has no spacing,
`--native`, or resampling options — see [GRID_RESAMPLING_DECISION.md](GRID_RESAMPLING_DECISION.md).

## Output

- One amplitude COG per polarization: `<granule>_<POL>_amp.tif` (and a co-registered phase
  COG `<granule>_<POL>_phs.tif` unless `--amp-only`)
  - Band 1: linear amplitude (`float32`), `NaN` = invalid/no-data
  - 512×512 tiling, DEFLATE + predictor 3, aligned to master-grid chunk boundaries

## Key facts about NISAR GSLC

- Already projected to **EPSG:3031** at **5×5 m** posting, with pixel edges on integer
  multiples of 5 m from the origin → this is a *placement + chunk snap*, **not** a CRS
  reprojection and **not** a resample.
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

### 2. Snap the target grid & check alignment (`nisar/regrid.py`, `nisar/extract.py`)

1. Compute the target geogrid: snap the granule's native extent to master-grid chunk
   boundaries via `grid.snap_bbox(expand=True)`, reusing the same snapping logic as BIOMASS
   (`compute_nisar_target_geogrid`). The fill margin expands to a whole number of 512×512
   chunks.
2. Compute the pixel offset of the granule origin within the snapped canvas. Because NISAR
   pixel edges lie on the 5 m master lattice, this offset **must be an integer**. If it is
   not, `process_single_polarization` raises `ValueError` rather than resampling — a
   subpixel shift is never performed. (The module contains no interpolation code, so no
   such path can exist.)

### 3. Mask, place & write COG (`nisar/extract.py`)

- Apply masks in the **complex** domain (detect last, so `|·|` never resamples):
  - `frequencyA/mask` (0 → NaN) to every polarization.
  - `inputDataExceptionMask` (≥1 → NaN) to **HV only**.
- **Place** each masked complex tile into the chunk-aligned canvas at the integer pixel
  offset (lossless windowed copy; the fill border stays NaN).
- Compute `amplitude = |placed complex|` (and phase = `angle(·)` if writing phase).
- Stream in 512×512 tiles for memory efficiency (files can be 100+ GB), write a temporary
  tiled GeoTIFF, then `gdal_translate -of COG` (512 blocksize, DEFLATE/ZLEVEL=1/PREDICTOR=3,
  BIGTIFF=YES, AVERAGE overviews).

## No `--native` / resampling modes

NISAR is always placed losslessly onto the shared 5×5 m master grid, which co-registers it
with BIOMASS by construction. There are deliberately no spacing, `--native`, or
resampling-kernel options: any of those would imply a resample, and the only safe operation
on an already-on-lattice GSLC is a lossless placement.
