# BIOMASS Workflow — Algorithm

Geocodes an ESA BIOMASS L1A SCS granule onto the master grid and writes an
amplitude-only Cloud-Optimized GeoTIFF per polarization.

## Input

- BIOMASS L1A SCS granule (directory or `.zip`), e.g. `BIO_S2_SCS__1S_*`
- DEM in EPSG:3031 covering the target extent (with margin)
- Polarization(s): HH, HV, VH, VV
- Grid spacing (default **5×5 m**; `--native` → **5×40 m**), margin, resampling params

## Output

- One amplitude COG per polarization: `<granule>_<POL>_amp.tif`
  - Band 1: linear amplitude (`float32`), `NaN` = invalid/no-data
  - 512×512 tiling, DEFLATE + predictor 3, aligned to master-grid chunk boundaries

## Algorithm

### 1. Compute chunk-aligned geogrid (`biomass/geogrid.py`)

1. Load the SLC via `biomass-reader` → radar grid, orbit, Doppler.
2. Sample the four radar-swath edges; project each point to EPSG:3031 with
   `isce3.geometry.rdr2geo` (assuming a 0 m height DEM interpolator) → footprint bbox.
3. Add a **margin** (default 5000 m) around the footprint so the swath sits comfortably
   inside the grid.
4. **Snap** the padded bbox outward to master-grid chunk boundaries via
   `grid.snap_bbox(expand=True)` → extent that is an integer number of 512×512 chunks and
   shares the master lattice. Emit geogrid params (extent, spacing, width, height, EPSG).

The snap step is what guarantees BIOMASS chunks co-register with NISAR chunks (same
origin + same spacing).

### 2. Geocode the complex SLC (`biomass/geocode.py`)

- Build `isce3.product.GeoGridParameters` from the geogrid (note: `spacing_y` negative for
  north-up).
- Run `isce3.geocode.geocode_slc` on the **complex** SLC:
  - `flatten=True`, `invalid_value = NaN+NaN·j`
  - geo2rdr threshold `1e-8`, ≤25 iterations
- Because geocoding operates on the complex signal directly, landing BIOMASS on the fine
  5×5 grid is a correct fine geocode — not a post-hoc interpolation of detected amplitude.
  This satisfies the "detect last" rule (see
  [GRID_RESAMPLING_DECISION.md](GRID_RESAMPLING_DECISION.md)).

### 3. Detect and write COG (`biomass/geocode.py`)

1. `amplitude = |complex|` as `float32` (phase discarded; amplitude-only product).
2. Write a temporary tiled GeoTIFF with the geogrid's affine transform and per-band
   metadata (polarization, acquisition time, units).
3. `gdal_translate … -of COG` with 512 blocksize, DEFLATE/ZLEVEL=1/PREDICTOR=3,
   BIGTIFF=YES, AVERAGE overviews.

## DEM coverage (fail-early)

Before any SLC load or geocoding, `check_dem_covers_grid()` validates a **provided** DEM
against the margined, chunk-aligned output grid and raises `DemCoverageError` if it does
not cover the swath. It checks two things (the grid bbox is reprojected into the DEM CRS,
so an EPSG:4326 DEM is handled):

1. **Extent** — the DEM must spatially contain the output grid.
2. **Valid data** — the DEM must actually hold valid elevation over the grid; an extent
   that merely overlaps is not enough (a DEM cropped to a different swath can be
   all-nodata here, which would otherwise yield 0 valid geocoded pixels).

On failure the message is: *"Provided DEM does not cover the output geocoded radar swath.
Either provide a DEM that corresponds to the input granule, or omit the --dem option to
let the algorithm auto-fetch the correct DEM."* Omitting `--dem` triggers the sardem
auto-download (`rift.dem.ensure_dem`), which fetches a DEM matching the footprint.

## Notes

- Resolution is unchanged by the 40→5 range upsampling; it only refines the lattice.
  BIOMASS effective range resolution stays ~46 m regardless of posting.
- After geocoding, the valid-pixel percentage is also reported as a secondary sanity check.
