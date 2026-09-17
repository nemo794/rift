# rift

⚠️ **Experimental**: This codebase is under active development and has not been extensively reviewed. The code has been generated primarily using AI assistance and should be used at your own risk.

**BIOMASS + NISAR → Antarctic master grid → inference**

`rift` puts ESA BIOMASS and NISAR SAR products on a common master grid over Antarctica
(EPSG:3031, 512×512 COG chunks), extracts amplitude Cloud-Optimized GeoTIFFs, and runs
inference to produce binary-mask COGs. It packages as two end-to-end MAAP DPS algorithms
(one per sensor).

## What it does

1. **Master grid** — a parameterized `AntarcticaGrid` (default **5×5 m**) that both sensors
   snap to, so their 512×512 chunks co-register. (BIOMASS `--native` → 5×40; NISAR is always
   placed on the 5×5 m grid.)
2. **BIOMASS** — geocode an L1A SCS granule with ISCE3 (`geocode_slc`, complex → detect last)
   → amplitude COG per polarization.
3. **NISAR** — extract frequency-A amplitude from a GSLC and **place** it losslessly onto the
   master grid (no resampling; NISAR pixel edges already lie on the 5 m lattice) → amplitude
   COG per polarization.
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
rift nisar2cog   --gslc NISAR_*.h5 --output out/            # lossless 5×5 placement
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
│   ├── nisar/{extract,regrid}.py      # freqA amplitude+masks; lossless placement on grid
│   ├── dem.py                  # ensure_dem() — provided DEM or sardem download
│   ├── infer/threshold.py      # placeholder inference: amp COG → binary-mask COG
│   ├── cogutil.py              # shared COG writer
│   ├── pipeline.py             # run_biomass_end_to_end / run_nisar_end_to_end
│   ├── validate.py             # geogrid alignment validation
│   └── cli.py                  # unified `rift` CLI (jsonargparse)
├── scripts/                    # Helper utilities (see below)
├── maap/{biomass_e2e,nisar_e2e}/      # MAAP DPS adapters (algorithm_config.yaml, run.sh, build-env.sh)
├── tests/                      # grid, nisar regrid, infer, pipeline
└── docs/                       # grid system, resampling decision, workflows, pipeline, API
```

## Helper Scripts

The `scripts/` directory contains utility scripts for common preprocessing tasks:

- **`download_dem_for_all_granules.py`** — Computes the union footprint of multiple BIOMASS 
  granules and downloads a covering DEM via `sardem`. Useful for preparing a shared DEM for 
  batch processing.

These scripts are provided as-is for convenience and are not part of the core `rift` package. 
They may not be actively maintained and should be reviewed before use in production workflows.

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

## Troubleshooting

### macOS Finder previews crash / consume many GB of memory

The amplitude and mask outputs are large (often >1 GB) DEFLATE-compressed float32 BigTIFF
COGs. They are valid COGs and open efficiently in GDAL-based tools like QGIS, which use the
embedded overviews. macOS Finder, however, renders previews through Apple's ImageIO/QuickLook,
which reads the **full-resolution** primary image and ignores the COG overviews. Selecting a
`.tif` in Finder (Preview pane, Gallery view, or icon thumbnails) can therefore decompress the
entire raster into memory — many GB — and hang or crash the system.

This is a macOS preview-rendering limitation, not a problem with the output files, and no COG
creation option changes ImageIO's behavior. Work around it on the Finder side:

- **Hide the Preview pane**: in Finder press **⌘⇧P** (View → Hide Preview). This is usually
  the specific culprit.
- **Use List (⌘2) or Column (⌘3) view** instead of Gallery view.
- **Disable icon thumbnails for the folder**: select the folder, press **⌘J** (Show View
  Options), uncheck **Show icon preview**, then optionally **Use as Defaults**.
- **Scriptable / system-wide** — stop Finder showing the preview pane by default and clear any
  wedged thumbnail cache:

  ```bash
  defaults write com.apple.finder ShowPreviewPane -bool false
  killall Finder
  qlmanage -r cache
  ```

## Requirements

- Python 3.9+
- ISCE3 (conda-forge)
- GDAL 3.6+
- NumPy, h5py
- Shapely, rasterio

See [environment.yaml](environment.yaml) for complete dependency list.

## Export Classification

Copyright 2026, by the California Institute of Technology. ALL RIGHTS
RESERVED. United States Government Sponsorship acknowledged. Any commercial
use must be negotiated with the Office of Technology Transfer at the
California Institute of Technology.

This software may be subject to U.S. export control laws. By accepting
this software, the user agrees to comply with all applicable U.S. export
laws and regulations. User has the responsibility to obtain export licenses,
or other export authority as may be required before exporting such
information to foreign countries or providing access to foreign persons.

If you have questions regarding this, please contact the JPL Software
Release Authority at x4-2458.

## License

This software was developed at the Jet Propulsion Laboratory, California Institute of Technology.

This software is licensed under your choice of BSD-3-Clause or Apache-2.0
licenses. The exact terms of each license can be found in the accompanying
[LICENSE-BSD-3-Clause.txt] and [LICENSE-Apache-2.0.txt] files, respectively.

[LICENSE-BSD-3-Clause.txt]: LICENSE-BSD-3-Clause.txt
[LICENSE-Apache-2.0.txt]: LICENSE-Apache-2.0.txt

SPDX-License-Identifier: BSD-3-Clause OR Apache-2.0

## Disclaimer

This software is provided "as is" without warranty of any kind, express or
implied, including but not limited to the warranties of merchantability,
fitness for a particular purpose and noninfringement. In no event shall the
authors or copyright holders be liable for any claim, damages or other
liability, whether in an action of contract, tort or otherwise, arising from,
out of or in connection with the software or the use or other dealings in
the software.

## Contact

For questions or issues, please open an issue on GitHub.
