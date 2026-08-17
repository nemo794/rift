# biomass-geocode

Geocode ESA BIOMASS L1A SCS granules to a master grid over Antarctica, producing Cloud-Optimized GeoTIFFs with perfectly aligned 512×512 pixel chunks across all processed scenes.

## Overview

This repository provides tools to geocode BIOMASS P-band SAR data to Antarctic Polar Stereographic (EPSG:3031) with consistent grid alignment. All output COGs share chunk boundaries, enabling efficient mosaicking and time-series analysis.

**Key Features:**
- **Master Grid Alignment**: All granules snap to a common 512×512 chunk grid
- **Cloud-Optimized GeoTIFFs**: Efficient cloud storage and partial reads
- **Flexible Output**: Amplitude-only or amplitude+phase
- **Memory Efficient**: Processes one granule at a time
- **Robust**: Comprehensive test suite included

## Installation

### 1. Create Conda Environment

```bash
conda env create -f environment.yaml
conda activate biomass_processing
```

### 2. Install biomass-reader

The `biomass-reader` package is not available on conda and must be installed from GitHub:

```bash
git clone https://github.com/scottstanie/biomass-reader.git
cd biomass-reader
pip install -e '.[ionosphere]'
cd ..
```

**Note**: If processing high-latitude data with coarse range resolution, you may want to use the fix-native-posting branch:
```bash
cd biomass-reader
git checkout fix-native-posting-coarse-resolution
pip install -e '.[ionosphere]'
```

### 3. Verify Installation

```bash
cd biomass-geocode
python tests/test_grid_system.py
```

You should see:
```
✓✓✓ ALL TESTS PASSED ✓✓✓
The Antarctica master grid system is working correctly!
```

## Quick Start

### Step 1: Compute Geogrid for Your Granule

```bash
python src/compute_biomass_geogrid.py \
    /path/to/BIOMASS_granule \
    --polarization HH \
    --margin 5000 \
    --output my_geogrid.json
```

This creates a geogrid JSON file that:
- Covers the granule footprint + margin
- Is snapped to the master grid chunk boundaries
- Can be reused for the same geographic area

### Step 2: Geocode the Granule

```bash
python src/geocode_biomass_custom_grid.py \
    --biomass-granule /path/to/BIOMASS_granule \
    --geogrid my_geogrid.json \
    --dem dem_epsg3031.tif \
    --output output_HH.tif \
    --polarization HH
```

**Optional**: Include phase band:
```bash
python src/geocode_biomass_custom_grid.py \
    --biomass-granule /path/to/BIOMASS_granule \
    --geogrid my_geogrid.json \
    --dem dem_epsg3031.tif \
    --output output_HH.tif \
    --polarization HH \
    --include-phase
```

### Step 3: Validate Grid Alignment (Optional)

```bash
python src/validate_grid_alignment.py geogrid1.json geogrid2.json geogrid3.json
```

## Master Grid Specification

The Antarctica master grid ensures all processed granules have aligned chunks:

| Parameter | Value |
|-----------|-------|
| **Projection** | EPSG:3031 (Antarctic Polar Stereographic) |
| **Origin** | (0, 0) at South Pole |
| **Pixel Spacing** | 5m × 40m (azimuth × range) |
| **Chunk Size** | 512 × 512 pixels |
| **Chunk Real-World Size** | 2.56 km × 20.48 km |
| **Full Grid Extent** | ±3,072,000 m |

**Why this matters**: When granules share chunk boundaries, you can efficiently mosaic them without reprocessing. Cloud-Optimized GeoTIFFs can be read partially by requesting only the chunks you need.

## Example Workflow

### Processing Multiple Granules Over the Same Area

```bash
# 1. Compute geogrid from first granule (with generous margin)
python src/compute_biomass_geogrid.py \
    granule1/ --margin 10000 --output area_geogrid.json

# 2. Geocode all granules to the same grid
for granule in granule1/ granule2/ granule3/; do
    basename=$(basename $granule)
    python src/geocode_biomass_custom_grid.py \
        --biomass-granule $granule \
        --geogrid area_geogrid.json \
        --dem dem_epsg3031.tif \
        --output ${basename}_HH.tif \
        --polarization HH
done

# 3. Validate alignment
python src/validate_grid_alignment.py area_geogrid.json
```

All output COGs will have perfectly aligned chunks and can be efficiently mosaicked.

## Repository Structure

```
biomass-geocode/
├── README.md                      # This file
├── LICENSE                        # Apache 2.0
├── environment.yaml               # Conda environment
├── pyproject.toml                 # Python package configuration
├── src/
│   ├── grid_utils.py              # Master grid dataclass and utilities
│   ├── compute_biomass_geogrid.py # Compute geogrid from granule
│   ├── geocode_biomass_custom_grid.py  # Main geocoding script
│   └── validate_grid_alignment.py # Validate geogrid alignment
├── tests/
│   └── test_grid_system.py        # Comprehensive test suite
├── docs/
│   ├── GRID_SYSTEM.md             # Grid system documentation
│   └── API.md                     # API reference
└── examples/
    ├── example_geogrid.json       # Example geogrid file
    └── process_multiple_granules.sh  # Batch processing example
```

## Dependencies

### Core Dependencies
- **isce3** ≥0.25: Radar geocoding engine
- **gdal** ≥3.8: Geospatial data handling
- **rasterio** ≥1.4: Python interface to GDAL
- **numpy** ≥1.25: Array operations
- **biomass-reader**: BIOMASS product reader (install separately from GitHub)

See `environment.yaml` for complete list.

## DEM Requirements

The DEM must be in EPSG:3031 and cover your processing area. For Antarctica:

```bash
# Download NISAR DEM for Antarctica (requires sardem package)
python -c "
from sardem import download_dem
download_dem(
    bounds=(-3072000, -3072000, 3072000, 3072000),
    epsg=3031,
    output='dem_antarctica_epsg3031.tif',
    dem_name='glo_90'
)
"
```

Or use the NISAR operational DEM if available.

## API Reference

### grid_utils.py

```python
from grid_utils import ANTARCTICA_GRID

# Print master grid info
ANTARCTICA_GRID.print_info()

# Snap a bounding box to chunk boundaries
bbox = {'x_min': 100000, 'x_max': 200000, 
        'y_min': -500000, 'y_max': -400000}
snapped = ANTARCTICA_GRID.snap_bbox(bbox, expand=True)

# Compute geogrid from bbox
geogrid = ANTARCTICA_GRID.compute_geogrid_for_bbox(
    bbox, margin_m=5000, snap_to_chunks=True
)

# Compute geogrid directly from granule
geogrid = ANTARCTICA_GRID.compute_geogrid_for_granule(
    'path/to/granule', polarization='HH', margin_m=5000
)

# Validate a geogrid
is_valid, message = ANTARCTICA_GRID.validate_geogrid(geogrid)
```

See `docs/API.md` for complete API documentation.

## Testing

Run the comprehensive test suite:

```bash
python tests/test_grid_system.py
```

Tests cover:
1. Master grid properties
2. Chunk boundary snapping
3. Geogrid computation
4. Multiple geogrid alignment
5. Chunk indexing
6. Edge cases
7. JSON serialization

## Output Format

Output GeoTIFFs are Cloud-Optimized (COG) with:

**Band Structure:**
- Band 1: Amplitude (linear, float32)
- Band 2: Phase in radians, -π to +π (float32, optional)

**Metadata:**
- Acquisition time
- Polarization
- Grid parameters
- Source granule information

**COG Parameters:**
- Block size: 512×512
- Compression: DEFLATE with predictor
- Overviews: Automatically generated

## Performance Notes

**Memory Usage:**
- Typical granule (1024×30000 pixels): ~2-4 GB RAM
- Large granule (2048×60000 pixels): ~8-10 GB RAM

**Processing Time:**
- Typical granule: 2-5 minutes on modern CPU
- Dominated by geocoding (isce3) and COG conversion (GDAL)

## Limitations

- **DEM Coverage**: DEM must fully cover the processing area
- **Projection**: Currently hardcoded to EPSG:3031 (can be modified in `grid_utils.py`)
- **Single Granule**: Processes one granule at a time (parallelization possible via shell)

## Contributing

Contributions welcome! Please:
1. Run tests before submitting: `python tests/test_grid_system.py`
2. Follow existing code style
3. Add tests for new features

## Citation

If you use this code in research, please cite:

```bibtex
@software{biomass_geocode,
  title = {biomass-geocode: Grid-aligned geocoding for BIOMASS SAR data},
  author = {[Your Name]},
  year = {2026},
  url = {https://github.com/[username]/biomass-geocode}
}
```

## License

Apache License 2.0 - See LICENSE file for details.

## Acknowledgments

- ESA BIOMASS mission for P-band SAR data
- JPL ISCE3 team for the geocoding engine
- Scott Stanie for biomass-reader package
- NISAR project for Antarctic DEM

## Contact

For questions or issues:
- Open an issue on GitHub
- Email: [your-email]

## Related Projects

- [biomass-reader](https://github.com/scottstanie/biomass-reader): BIOMASS product reader
- [isce3](https://github.com/isce-framework/isce3): InSAR Scientific Computing Environment
- [nisarqa](https://github.com/isce-framework/nisarqa): NISAR quality assurance (similar repo structure)
