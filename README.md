# biomass-geocode

**BIOMASS Geocoding Toolkit for Antarctic Applications**

Tools to geocode ESA BIOMASS L1A SCS granules to a master grid over Antarctica, producing Cloud-Optimized GeoTIFFs with perfectly aligned 512×512 pixel chunks.

## Features

- **Master Grid Alignment**: All granules snap to a common 512×512 chunk grid in EPSG:3031
- **Cloud-Optimized Output**: GeoTIFFs optimized for cloud storage and processing
- **Immutable Grid Definition**: Type-safe `AntarcticaGrid` dataclass prevents accidental misconfiguration
- **Comprehensive Testing**: Full test suite with 7 test cases (100% passing)
- **Complete Documentation**: API reference, grid system docs, and examples

## Quick Start

### Installation

See [INSTALL.md](INSTALL.md) for detailed installation instructions.

```bash
# Create conda environment
conda env create -f environment.yaml
conda activate biomass-geocode

# Install package
pip install -e .
```

### Basic Usage

```python
from biomass_geocode.grid_utils import ANTARCTICA_GRID

# Compute geogrid for a BIOMASS granule
geogrid = ANTARCTICA_GRID.compute_geogrid_for_granule(
    granule_path="path/to/BIO_*.zip",
    spacing_m=100
)

# Save geogrid for geocoding
with open("geogrid.json", "w") as f:
    json.dump(geogrid, f, indent=2)
```

### Geocoding a Granule

```bash
# Geocode BIOMASS SCS data to custom grid
python src/geocode_biomass_custom_grid.py \
    path/to/BIO_*.zip \
    /path/to/dem.tif \
    geogrid.json \
    output_HH.tif \
    --polarization HH
```

## Repository Structure

```
biomass-geocode/
├── README.md                           # This file
├── INSTALL.md                          # Detailed installation instructions
├── pyproject.toml                      # Python package configuration
├── environment.yaml                    # Conda environment specification
├── src/
│   ├── __init__.py
│   ├── grid_utils.py                   # Master grid dataclass (AntarcticaGrid)
│   ├── compute_biomass_geogrid.py      # Compute geogrid from granule footprint
│   ├── geocode_biomass_custom_grid.py  # Main geocoding script
│   └── validate_grid_alignment.py      # Validate geogrid alignment
├── tests/
│   └── test_grid_system.py             # Comprehensive test suite
├── docs/
│   ├── GRID_SYSTEM.md                  # Grid system documentation
│   └── API.md                          # Complete API reference
└── examples/
    ├── example_geogrid.json            # Example geogrid file
    └── process_multiple_granules.sh    # Batch processing script
```

## Core Components

### Grid System

The `AntarcticaGrid` dataclass defines the master grid over Antarctica:

- **EPSG**: 3031 (Antarctic Polar Stereographic)
- **Bounds**: (-2.7M, -2.2M) to (2.8M, 2.3M) meters
- **Chunk Size**: 512×512 pixels
- **Grid Spacing**: Configurable (typically 100m for BIOMASS)

All geocoded granules align to this common grid, ensuring:
- Pixel boundaries match across granules
- Chunks align perfectly for cloud-optimized access
- Consistent geotransforms for stacking and mosaicking

### Main Scripts

1. **`compute_biomass_geogrid.py`**: Compute geogrid JSON from granule footprint
2. **`geocode_biomass_custom_grid.py`**: Geocode BIOMASS SCS data to grid
3. **`validate_grid_alignment.py`**: Validate geogrid alignment

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
