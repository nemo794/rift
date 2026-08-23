# rift

**BIOMASS + NISAR → Antarctic master grid → inference**

`rift` puts ESA BIOMASS and NISAR SAR products on a common master grid over Antarctica
(EPSG:3031, 512×512 COG chunks), extracts amplitude Cloud-Optimized GeoTIFFs, and runs
inference to produce binary-mask COGs. It packages as two end-to-end MAAP DPS algorithms
(one per sensor).

## What it does

1. **Master grid** — a parameterized `AntarcticaGrid` (default **5×5 m**) that both sensors
   snap to, so their 512×512 chunks co-register. (`--native` → BIOMASS 5×40, NISAR 5×5.)
2. **BIOMASS** — geocode an L1A SCS granule with ISCE3 (`geocode_slc`, complex → detect last)
   → amplitude COG per polarization.
3. **NISAR** — extract frequency-A amplitude from a GSLC, regrid onto the master grid in the
   **complex domain** with anti-aliasing → amplitude COG per polarization.
4. **Inference** — placeholder binary-threshold model: one amplitude COG → one binary-mask COG
   (to be replaced by the trained model).

See [docs/GRID_RESAMPLING_DECISION.md](docs/GRID_RESAMPLING_DECISION.md),
[docs/BIOMASS_WORKFLOW.md](docs/BIOMASS_WORKFLOW.md),
[docs/NISAR_WORKFLOW.md](docs/NISAR_WORKFLOW.md), and [docs/PIPELINE.md](docs/PIPELINE.md).

## Quick Start

### Installation

See [INSTALL.md](INSTALL.md) for details.

```bash
conda env create -f environment.yaml
conda activate rift
# biomass-reader (BIOMASS workflow only; not on conda):
git clone https://github.com/scottstanie/biomass-reader.git
pip install -e './biomass-reader[ionosphere]'
pip install -e .
```

### CLI

```bash
# End-to-end (one MAAP job per granule): granule → amplitude COGs → mask COGs
rift biomass-e2e --granule BIO_*.zip --output out/ [--dem dem.tif] --threshold 0.5
rift nisar-e2e   --gslc NISAR_*GSLC*.h5 --output out/ --threshold 0.5

# Individual steps (local dev/debug)
rift biomass2cog --granule BIO_*.zip --dem dem.tif --output out/ --pols '[HH,HV]'
rift nisar2cog   --gslc NISAR_*.h5 --output out/            # default 5×5
rift nisar2cog   --gslc NISAR_*.h5 --output out/ --x-spacing 5 --y-spacing 40
rift biomass-infer --input amp.tif --output mask.tif --threshold 0.5
rift validate --geogrids '[geogrid1.json,geogrid2.json]'
```

`--keep-intermediates` (e2e only) keeps amplitude COGs in the output directory (default:
deleted to minimize egress). Each e2e run also writes a `*_e2e_config.json`.

### Python

```python
from rift.grid import ANTARCTICA_GRID
from rift.pipeline import run_nisar_end_to_end

biomass_grid = ANTARCTICA_GRID.with_spacing(5, 40)   # BIOMASS-native
run_nisar_end_to_end("NISAR_*.h5", "out/", threshold=0.5)
```

## Repository Structure

```
rift/
├── README.md · INSTALL.md · pyproject.toml · environment.yaml
├── src/rift/
│   ├── grid.py                 # AntarcticaGrid (parameterized spacing, default 5×5)
│   ├── biomass/{geogrid,geocode}.py   # footprint→geogrid; ISCE3 geocode→amplitude COG
│   ├── nisar/{extract,regrid}.py      # freqA amplitude+masks; complex regrid to grid
│   ├── dem.py                  # ensure_dem() — provided DEM or sardem download
│   ├── infer/threshold.py      # placeholder inference: amp COG → binary-mask COG
│   ├── cogutil.py              # shared COG writer
│   ├── pipeline.py             # run_biomass_end_to_end / run_nisar_end_to_end
│   ├── validate.py             # geogrid alignment validation
│   └── cli.py                  # unified `rift` CLI (jsonargparse)
├── maap/{biomass_e2e,nisar_e2e}/      # MAAP DPS adapters (algorithm_config.yaml, run.sh, build-env.sh)
├── tests/                      # grid, nisar regrid, infer, pipeline
└── docs/                       # grid system, resampling decision, workflows, pipeline, API
```

## Core Components

### Grid System

The `AntarcticaGrid` dataclass defines the master grid over Antarctica:

- **EPSG**: 3031 (Antarctic Polar Stereographic)
- **Chunk Size**: 512×512 pixels
- **Grid Spacing**: parameterized; default **5×5 m** (shared BIOMASS/NISAR grid).
  `ANTARCTICA_GRID.with_spacing(5, 40)` builds the BIOMASS-native grid.

All geocoded/regridded granules align to this common grid, ensuring pixel boundaries and
COG chunks match across granules and sensors for stacking, mosaicking, and inference.

See [docs/API.md](docs/API.md) for complete API documentation.

## Examples

### Process a Single Granule

```bash
# 1. Compute geogrid
python src/compute_biomass_geogrid.py \
    BIO_S2_SCS__1S_*.zip \
    100 \
    geogrid.json

# 2. Geocode
python src/geocode_biomass_custom_grid.py \
    BIO_S2_SCS__1S_*.zip \
    dem_epsg3031.tif \
    geogrid.json \
    biomass_HH.tif \
    --polarization HH
```

### Process Multiple Granules

See [examples/process_multiple_granules.sh](examples/process_multiple_granules.sh) for a batch processing script.

## Testing

```bash
# Run test suite
pytest tests/test_grid_system.py -v

# All 7 tests should pass:
# - test_grid_initialization
# - test_snap_bbox_basic
# - test_snap_bbox_already_aligned
# - test_compute_geogrid_basic
# - test_compute_geogrid_validation
# - test_antarctica_grid_singleton
# - test_validate_geogrid
```

## Documentation

- [INSTALL.md](INSTALL.md): Installation instructions
- [docs/GRID_SYSTEM.md](docs/GRID_SYSTEM.md): Grid system overview
- [docs/API.md](docs/API.md): Complete API reference
- [REPOSITORY_SUMMARY.md](REPOSITORY_SUMMARY.md): Repository setup details

## Requirements

- Python 3.9+
- ISCE3 (conda-forge)
- GDAL 3.6+
- NumPy, h5py
- Shapely, rasterio

See [environment.yaml](environment.yaml) for complete dependency list.

## License

This software was developed at the Jet Propulsion Laboratory, California Institute of Technology.

## Contact

For questions or issues, please open an issue on GitHub.
