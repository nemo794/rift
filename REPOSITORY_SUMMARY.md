# Repository Setup Summary

## Overview

The `rift` repository is now ready for GitHub! This repository provides tools to geocode ESA BIOMASS L1A SCS granules to a master grid over Antarctica, producing Cloud-Optimized GeoTIFFs with perfectly aligned 512×512 pixel chunks.

## Repository Structure

```
rift/
├── README.md                      # Main documentation with quick start
├── INSTALL.md                     # Detailed installation instructions
├── pyproject.toml                 # Python package configuration
├── environment.yaml               # Conda environment specification
├── .gitignore                     # Git ignore patterns
├── src/
│   ├── __init__.py                # Package initialization
│   ├── grid_utils.py              # Master grid dataclass (AntarcticaGrid)
│   ├── compute_biomass_geogrid.py # Compute geogrid from granule footprint
│   ├── geocode_biomass_custom_grid.py  # Main geocoding script
│   └── validate_grid_alignment.py # Validate geogrid alignment
├── tests/
│   └── test_grid_system.py        # Comprehensive test suite (7 tests, all passing)
├── docs/
│   ├── GRID_SYSTEM.md             # Grid system documentation
│   └── API.md                     # Complete API reference
└── examples/
    ├── example_geogrid.json       # Example geogrid file
    └── process_multiple_granules.sh  # Batch processing script
```

## Key Features

1. **Master Grid Alignment**: All granules snap to common 512×512 chunk grid
2. **Immutable Grid Definition**: `AntarcticaGrid` dataclass (frozen=True) prevents accidental modification
3. **Comprehensive Testing**: 7 test cases covering all functionality (100% passing)
4. **Complete Documentation**: README, installation guide, API reference, and grid system docs
5. **Working Examples**: Example geogrid and batch processing script
6. **Professional Structure**: Follows nisarqa repository pattern

## Core Components

### 1. grid_utils.py
- **AntarcticaGrid** dataclass: Immutable grid configuration
- **ANTARCTICA_GRID** singleton: Pre-configured instance
- **Key methods**:
  - `snap_bbox()`: Snap bounding boxes to chunk boundaries
  - `compute_geogrid_for_bbox()`: Create geogrids from bounding boxes
  - `compute_geogrid_for_granule()`: High-level convenience method
  - `validate_geogrid()`: Verify grid alignment
  - `get_chunk_indices()`: Get chunk indices for coordinates

### 2. compute_biomass_geogrid.py
- Computes radar footprint from BIOMASS granule
- Adds margin and snaps to master grid
- Outputs JSON geogrid file

### 3. geocode_biomass_custom_grid.py
- Geocodes BIOMASS granule using isce3
- Creates Cloud-Optimized GeoTIFF
- Optional amplitude-only or amplitude+phase output

### 4. validate_grid_alignment.py
- Validates single or multiple geogrids
- Checks alignment to master grid
- Verifies pairwise compatibility

## Test Coverage

All 7 tests pass:
1. ✓ Master grid properties
2. ✓ Chunk boundary snapping (positive, negative, mixed coordinates)
3. ✓ Geogrid computation
4. ✓ Multiple geogrid alignment
5. ✓ Chunk indexing
6. ✓ Edge cases (aligned, small, large bboxes)
7. ✓ JSON serialization

## Grid Specification

| Parameter | Value |
|-----------|-------|
| **Projection** | EPSG:3031 (Antarctic Polar Stereographic) |
| **Origin** | (0, 0) at South Pole |
| **Pixel Spacing** | 5m × 40m (azimuth × range) |
| **Chunk Size** | 512 × 512 pixels |
| **Chunk Real-World Size** | 2.56 km × 20.48 km |
| **Full Grid Extent** | ±3,072,000 m |

## Dependencies

### Core (via conda)
- isce3 ≥0.25 (geocoding engine)
- gdal ≥3.8 (geospatial data)
- rasterio ≥1.4 (raster I/O)
- numpy ≥1.25 (array operations)

### Special Installation
- **biomass-reader**: Must be installed separately from GitHub
  ```bash
  git clone https://github.com/scottstanie/biomass-reader.git
  pip install -e './biomass-reader[ionosphere]'
  ```

## Quick Start

```bash
# 1. Create environment
conda env create -f environment.yaml
conda activate biomass_processing

# 2. Install biomass-reader
git clone https://github.com/scottstanie/biomass-reader.git
cd biomass-reader && pip install -e '.[ionosphere]' && cd ..

# 3. Test installation
python tests/test_grid_system.py

# 4. Compute geogrid
python src/compute_biomass_geogrid.py /path/to/granule --output geogrid.json

# 5. Geocode
python src/geocode_biomass_custom_grid.py \
    --biomass-granule /path/to/granule \
    --geogrid geogrid.json \
    --dem dem_epsg3031.tif \
    --output output.tif \
    --polarization HH
```

## Before Publishing to GitHub

### 1. Update Placeholders

Edit these files to replace placeholder text:

**pyproject.toml:**
- Line 9: `authors = [{name = "Your Name", email = "your.email@example.com"}]`
- Line 20: `Homepage = "https://github.com/yourusername/rift"`
- Lines 21-23: Update URLs with your GitHub username

**README.md:**
- Line 245: Update citation with your name/details
- Line 259: Update contact email

### 2. Initialize Git Repository

```bash
cd rift
git init
git add .
git commit -m "Initial commit: BIOMASS geocoding tools for Antarctica"
```

### 3. Create GitHub Repository

1. Go to https://github.com/new
2. Repository name: `rift`
3. Description: "Geocode ESA BIOMASS L1A SCS granules to a master grid over Antarctica"
4. Public or Private (your choice)
5. Do NOT initialize with README (we already have one)

### 4. Push to GitHub

```bash
git remote add origin https://github.com/yourusername/rift.git
git branch -M main
git push -u origin main
```

### 5. Add Topics (on GitHub)

Suggested topics for discoverability:
- `biomass`
- `sar`
- `geocoding`
- `antarctica`
- `isce3`
- `remote-sensing`
- `python`
- `geospatial`

## Optional Enhancements

Consider adding these in future versions:

1. **GitHub Actions**: CI/CD for automated testing
2. **Docker**: Containerized environment
3. **Example Notebooks**: Jupyter notebooks with tutorials
4. **Pre-commit Hooks**: Code formatting and linting
5. **Release Tags**: Versioned releases on GitHub
6. **DOI**: Zenodo integration for citable releases

## Differences from nisarqa Structure

Following nisarqa's pattern, but with adaptations:

- **License**: No license file (as requested)
- **Simplified**: Focused on single task (geocoding) vs. QA suite
- **Grid System**: Custom dataclass-based grid alignment
- **Documentation**: Complete API docs and grid system guide
- **Tests**: Standalone test suite (not pytest-based)

## Files Not Included

The following working directory files were intentionally excluded:
- BIOMASS granule data (*.zip, BIO_* directories)
- DEM files (*.tif)
- Output products (test results, logs)
- Development artifacts (.claude/, __pycache__)
- Documentation drafts (SUMMARY_*.md, DEBUGGING_*.md, etc.)

These are covered by .gitignore patterns.

## Verification Checklist

- [x] All Python files copied to src/
- [x] Test suite runs successfully (7/7 tests pass)
- [x] environment.yaml includes all dependencies
- [x] README.md has complete quick start
- [x] INSTALL.md has detailed instructions
- [x] API.md documents all functions
- [x] GRID_SYSTEM.md explains the grid
- [x] Example files included
- [x] .gitignore configured
- [x] pyproject.toml configured
- [x] Repository structure matches nisarqa pattern

## Next Steps

1. Update placeholder text in files (see "Before Publishing" section)
2. Review and customize README.md for your use case
3. Initialize git repository
4. Create GitHub repository
5. Push to GitHub
6. Share with collaborators!

---

**Repository is ready for GitHub!** 🚀
