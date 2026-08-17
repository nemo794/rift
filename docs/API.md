# API Reference

## grid_utils.py

### AntarcticaGrid Class

The `AntarcticaGrid` dataclass encapsulates the master grid parameters and provides methods for chunk-aligned geocoding.

#### Instance: ANTARCTICA_GRID

```python
from grid_utils import ANTARCTICA_GRID
```

A singleton instance pre-configured with Antarctica master grid parameters.

#### Properties

##### Basic Parameters

```python
ANTARCTICA_GRID.epsg          # 3031 (Antarctic Polar Stereographic)
ANTARCTICA_GRID.x_posting     # 5.0 meters
ANTARCTICA_GRID.y_posting     # 40.0 meters
ANTARCTICA_GRID.chunk_pixels  # 512
```

##### Grid Extent

```python
ANTARCTICA_GRID.x_min         # -3,072,000.0 m
ANTARCTICA_GRID.x_max         # 3,072,000.0 m
ANTARCTICA_GRID.y_min         # -3,072,000.0 m
ANTARCTICA_GRID.y_max         # 3,072,000.0 m
ANTARCTICA_GRID.origin_x      # 0.0
ANTARCTICA_GRID.origin_y      # 0.0
```

##### Computed Properties

```python
ANTARCTICA_GRID.chunk_size_x  # 2,560 m (512 * 5m)
ANTARCTICA_GRID.chunk_size_y  # 20,480 m (512 * 40m)
ANTARCTICA_GRID.width         # 1,228,800 pixels (full grid)
ANTARCTICA_GRID.height        # 153,600 pixels (full grid)
ANTARCTICA_GRID.n_chunks_x    # 2,400 chunks
ANTARCTICA_GRID.n_chunks_y    # 300 chunks
```

#### Methods

##### snap_coordinate()

Snap a single coordinate to the nearest chunk boundary.

```python
def snap_coordinate(value: float, chunk_size: float, mode: str = 'floor') -> float
```

**Parameters:**
- `value`: Coordinate value in meters
- `chunk_size`: Chunk size in meters (use `chunk_size_x` or `chunk_size_y`)
- `mode`: `'floor'` (snap down) or `'ceil'` (snap up)

**Returns:** Snapped coordinate aligned to chunk boundary

**Example:**
```python
# Snap X coordinate down to chunk boundary
x_snapped = ANTARCTICA_GRID.snap_coordinate(123456.7, ANTARCTICA_GRID.chunk_size_x, 'floor')
# Returns: 122880.0

# Snap Y coordinate up to chunk boundary
y_snapped = ANTARCTICA_GRID.snap_coordinate(-987654.3, ANTARCTICA_GRID.chunk_size_y, 'ceil')
# Returns: -983040.0
```

##### snap_bbox()

Snap a bounding box to master grid chunk boundaries.

```python
def snap_bbox(bbox: dict, expand: bool = True) -> dict
```

**Parameters:**
- `bbox`: Dictionary with keys `x_min`, `x_max`, `y_min`, `y_max` (meters, EPSG:3031)
- `expand`: If `True`, expand bbox to cover entire chunks. If `False`, contract to fit within chunks.

**Returns:** Snapped bounding box dictionary

**Example:**
```python
bbox = {'x_min': 123456.7, 'x_max': 234567.8,
        'y_min': -987654.3, 'y_max': -876543.2}

# Expand to cover whole chunks (most common)
snapped = ANTARCTICA_GRID.snap_bbox(bbox, expand=True)
# Returns: {'x_min': 122880.0, 'x_max': 235520.0,
#           'y_min': -1003520.0, 'y_max': -860160.0}

# Contract to fit within chunks (rarely used)
contracted = ANTARCTICA_GRID.snap_bbox(bbox, expand=False)
```

##### compute_geogrid_for_bbox()

Compute geogrid parameters from a bounding box.

```python
def compute_geogrid_for_bbox(
    bbox: dict,
    margin_m: float = 0.0,
    snap_to_chunks: bool = True
) -> dict
```

**Parameters:**
- `bbox`: Bounding box dictionary
- `margin_m`: Margin to add around bbox before snapping (meters)
- `snap_to_chunks`: If `True`, snap bbox to chunk boundaries (recommended)

**Returns:** Geogrid parameters dictionary compatible with `geocode_biomass_custom_grid.py`

**Example:**
```python
bbox = {'x_min': 100000, 'x_max': 200000,
        'y_min': -500000, 'y_max': -400000}

geogrid = ANTARCTICA_GRID.compute_geogrid_for_bbox(
    bbox, 
    margin_m=5000,
    snap_to_chunks=True
)

# geogrid contains:
# {
#   'epsg': 3031,
#   'x_min': 97280.0,    # Snapped
#   'x_max': 202240.0,   # Snapped
#   'y_min': -512000.0,  # Snapped
#   'y_max': -389120.0,  # Snapped
#   'x_posting': 5.0,
#   'y_posting': 40.0,
#   'width': 20992,      # Multiple of 512
#   'height': 3072       # Multiple of 512
# }
```

##### compute_geogrid_for_granule()

High-level convenience method: compute chunk-aligned geogrid directly from a BIOMASS granule.

```python
def compute_geogrid_for_granule(
    granule_path: Path,
    polarization: str = 'HH',
    margin_m: float = 5000.0,
    snap_to_chunks: bool = True
) -> dict
```

**Parameters:**
- `granule_path`: Path to BIOMASS granule directory or .zip file
- `polarization`: Polarization to use for footprint computation
- `margin_m`: Margin to add around footprint (meters)
- `snap_to_chunks`: If `True`, snap to chunk boundaries (recommended)

**Returns:** Geogrid parameters dictionary

**Example:**
```python
from pathlib import Path

geogrid = ANTARCTICA_GRID.compute_geogrid_for_granule(
    Path('/data/BIO_S2_SCS__1S_20251223T233738.../'),
    polarization='HH',
    margin_m=5000,
    snap_to_chunks=True
)

# Save for use in geocoding
import json
with open('geogrid.json', 'w') as f:
    json.dump(geogrid, f, indent=2)
```

##### get_chunk_indices()

Get chunk indices for a coordinate.

```python
def get_chunk_indices(x: float, y: float) -> tuple[int, int]
```

**Parameters:**
- `x`: X coordinate in meters (EPSG:3031)
- `y`: Y coordinate in meters (EPSG:3031)

**Returns:** Tuple `(chunk_x, chunk_y)` — chunk indices relative to origin

**Example:**
```python
# Origin is in chunk (0, 0)
assert ANTARCTICA_GRID.get_chunk_indices(0, 0) == (0, 0)

# Positive quadrant
assert ANTARCTICA_GRID.get_chunk_indices(2560, 20480) == (1, 1)

# Negative quadrant
assert ANTARCTICA_GRID.get_chunk_indices(-2560, -20480) == (-1, -1)

# Find which chunk a coordinate falls in
chunk_x, chunk_y = ANTARCTICA_GRID.get_chunk_indices(123456, -987654)
print(f"Coordinate is in chunk ({chunk_x}, {chunk_y})")
```

##### get_chunk_bounds()

Get bounding box for a specific chunk.

```python
def get_chunk_bounds(chunk_x: int, chunk_y: int) -> dict
```

**Parameters:**
- `chunk_x`: Chunk index in X direction
- `chunk_y`: Chunk index in Y direction

**Returns:** Bounding box dictionary

**Example:**
```python
# Get bounds of origin chunk
bounds = ANTARCTICA_GRID.get_chunk_bounds(0, 0)
# Returns: {'x_min': 0, 'x_max': 2560, 'y_min': 0, 'y_max': 20480}

# Get bounds of chunk in negative quadrant
bounds = ANTARCTICA_GRID.get_chunk_bounds(-1, -1)
# Returns: {'x_min': -2560, 'x_max': 0, 'y_min': -20480, 'y_max': 0}
```

##### validate_geogrid()

Validate that a geogrid is properly aligned to master grid chunks.

```python
def validate_geogrid(geogrid: dict) -> tuple[bool, str]
```

**Parameters:**
- `geogrid`: Geogrid parameters dictionary

**Returns:** Tuple `(is_valid, message)` where `is_valid` is a boolean and `message` describes the result

**Example:**
```python
geogrid = {...}  # Load from JSON

is_valid, message = ANTARCTICA_GRID.validate_geogrid(geogrid)

if is_valid:
    print(f"✓ {message}")
else:
    print(f"✗ Validation failed:")
    print(message)
```

Checks performed:
- EPSG matches (3031)
- Pixel spacing matches (5m × 40m)
- All boundaries align to chunk boundaries
- Dimensions are multiples of 512

##### print_geogrid_info()

Print human-readable geogrid information with chunk alignment details.

```python
def print_geogrid_info(geogrid: dict) -> None
```

**Example:**
```python
geogrid = ANTARCTICA_GRID.compute_geogrid_for_bbox(bbox)
ANTARCTICA_GRID.print_geogrid_info(geogrid)

# Output:
# Geogrid Information:
#   EPSG: 3031
#   Posting: 5.0m × 40.0m
#   Dimensions: 20992 × 3072 pixels
#   ...
```

##### print_info()

Print information about the master grid.

```python
def print_info() -> None
```

**Example:**
```python
ANTARCTICA_GRID.print_info()

# Output:
# ======================================================================
# ANTARCTICA MASTER GRID
# ======================================================================
# 
# Projection:
#   EPSG: 3031 (Antarctic Polar Stereographic)
#   ...
```

---

## compute_biomass_geogrid.py

### compute_biomass_footprint()

Compute the geographic footprint of a BIOMASS granule.

```python
def compute_biomass_footprint(
    granule_path: Path,
    polarization: str = 'HH',
    samples_per_edge: int = 10
) -> dict
```

**Parameters:**
- `granule_path`: Path to BIOMASS granule directory or .zip file
- `polarization`: Polarization to analyze
- `samples_per_edge`: Number of sample points per edge (higher = more accurate)

**Returns:** Bounding box in EPSG:3031

**Example:**
```python
from pathlib import Path
from compute_biomass_geogrid import compute_biomass_footprint

bbox = compute_biomass_footprint(
    Path('/data/BIO_S2_SCS__1S_20251223T233738.../'),
    polarization='HH'
)

# Returns:
# {
#   'x_min': 123456.7,
#   'x_max': 234567.8,
#   'y_min': -987654.3,
#   'y_max': -876543.2
# }
```

### create_geogrid_params()

Create geogrid parameters covering a bounding box.

```python
def create_geogrid_params(
    bbox: dict,
    margin_m: float = 5000,
    snap_to_master_grid: bool = True
) -> dict
```

**Parameters:**
- `bbox`: Bounding box dictionary
- `margin_m`: Margin to add around bbox (meters)
- `snap_to_master_grid`: If `True`, snap to master grid chunks

**Returns:** Geogrid parameters dictionary

---

## geocode_biomass_custom_grid.py

### Command-Line Interface

```bash
python src/geocode_biomass_custom_grid.py \
    --biomass-granule /path/to/granule \
    --geogrid geogrid.json \
    --dem dem_epsg3031.tif \
    --output output.tif \
    --polarization HH \
    [--include-phase]
```

**Arguments:**
- `--biomass-granule`: BIOMASS L1A SCS granule directory or .zip file
- `--geogrid`: JSON file with geogrid parameters
- `--dem`: DEM file in EPSG:3031
- `--output`: Output COG file
- `--polarization`: Polarization (HH, HV, VH, VV)
- `--include-phase`: Include phase band (default: amplitude only)

**Output:**
- Band 1: Amplitude (float32, linear)
- Band 2: Phase (float32, radians) [if --include-phase]

---

## validate_grid_alignment.py

### Command-Line Interface

```bash
# Validate single geogrid
python src/validate_grid_alignment.py geogrid1.json

# Validate multiple geogrids
python src/validate_grid_alignment.py geogrid1.json geogrid2.json geogrid3.json

# Validate all geogrids in directory
python src/validate_grid_alignment.py geogrids/*.json
```

**Output:** Validation report showing:
- Individual geogrid alignment status
- Pairwise overlap compatibility (for multiple geogrids)
- Chunk information and coverage

---

## Geogrid JSON Format

Geogrid files are JSON dictionaries with the following structure:

```json
{
  "epsg": 3031,
  "x_min": 97280.0,
  "x_max": 202240.0,
  "y_min": -512000.0,
  "y_max": -389120.0,
  "x_posting": 5.0,
  "y_posting": 40.0,
  "width": 20992,
  "height": 3072
}
```

All values are in meters (except EPSG code and pixel dimensions).
