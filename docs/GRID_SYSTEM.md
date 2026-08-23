# Antarctica Master Grid System

> **Note — default spacing is now 5×5 m.** Pixel spacing is a parameter
> (`x_posting`/`y_posting`); the default `ANTARCTICA_GRID` is **5×5 m** so BIOMASS and NISAR
> co-register at the chunk level. Tables/examples below showing **5×40 m** (chunk_size_y =
> 20,480 m) describe the **BIOMASS-native** grid, built via `ANTARCTICA_GRID.with_spacing(5, 40)`.
> See [GRID_RESAMPLING_DECISION.md](GRID_RESAMPLING_DECISION.md).

## Overview

The Antarctica master grid is a reference grid that ensures all geocoded BIOMASS and NISAR granules produce Cloud-Optimized GeoTIFFs (COGs) with perfectly aligned 512×512 pixel chunks. This alignment is critical for efficient mosaicking, time-series analysis, and cloud-based data access.

## Master Grid Specification

### Projection and Extent

| Parameter | Value | Notes |
|-----------|-------|-------|
| **Projection** | EPSG:3031 | Antarctic Polar Stereographic |
| **Origin** | (0, 0) | South Pole in EPSG:3031 coordinates |
| **X Extent** | -3,072,000 to +3,072,000 m | 6,144 km total width |
| **Y Extent** | -3,072,000 to +3,072,000 m | 6,144 km total height |

### Pixel Spacing

| Direction | Spacing | Rationale |
|-----------|---------|-----------|
| **X (Azimuth)** | 5 m | Matches BIOMASS native azimuth resolution (~6-10m) |
| **Y (Range)** | 40 m | Matches BIOMASS native range resolution (~25-50m at high latitudes) |

**Why different spacing?** BIOMASS SAR has anisotropic resolution: fine in azimuth (along-track), coarse in range (across-track). Using different pixel spacings preserves native resolution in both directions without excessive upsampling or downsampling.

### Chunk Configuration

| Parameter | Value | Calculation |
|-----------|-------|-------------|
| **Chunk Size (pixels)** | 512 × 512 | Standard COG block size |
| **Chunk Size X (meters)** | 2,560 m | 512 × 5m = 2.56 km |
| **Chunk Size Y (meters)** | 20,480 m | 512 × 40m = 20.48 km |
| **Total Chunks** | 2,400 × 300 | 720,000 chunks cover full Antarctica |

## How Chunk Alignment Works

### The Problem

Without a master grid, each granule might be geocoded to an arbitrary extent:

```
Granule A: x_min = 123,456.7 m
Granule B: x_min = 123,789.2 m
```

When creating COGs with 512×512 chunks, the chunk boundaries would be:

```
Granule A chunks start at: 123,456.7, 123,456.7 + 2,560, ...
Granule B chunks start at: 123,789.2, 123,789.2 + 2,560, ...
```

These don't align! Mosaicking or stacking these COGs would require resampling.

### The Solution

The master grid defines chunk boundaries relative to origin (0, 0):

```
Chunk boundaries in X: ..., -5,120, -2,560, 0, 2,560, 5,120, ...
Chunk boundaries in Y: ..., -40,960, -20,480, 0, 20,480, 40,960, ...
```

By snapping all granule extents to these boundaries:

```
Granule A: x_min = 122,880 (snapped down to nearest chunk boundary)
Granule B: x_min = 122,880 (also snapped to same boundary)
```

Now both granules have identical chunk boundaries in their overlap region!

## Chunk Snapping Algorithm

The `ANTARCTICA_GRID.snap_bbox()` method implements chunk-aligned snapping:

### Expand Mode (default)

Expands the bounding box outward to cover whole chunks:

```python
x_min_snapped = floor(x_min / 2560) * 2560
x_max_snapped = ceil(x_max / 2560) * 2560
y_min_snapped = floor(y_min / 20480) * 20480
y_max_snapped = ceil(y_max / 20480) * 20480
```

**Example:**
```
Original:  [123,456.7, 234,567.8] m
Snapped:   [122,880.0, 235,520.0] m
```

### Contract Mode

Contracts the bounding box inward to fit within chunks (rarely used):

```python
x_min_snapped = ceil(x_min / 2560) * 2560
x_max_snapped = floor(x_max / 2560) * 2560
```

## Workflow Integration

### 1. Compute Footprint

First, compute the granule's radar footprint in EPSG:3031:

```python
from compute_biomass_geogrid import compute_biomass_footprint

bbox = compute_biomass_footprint('granule/', polarization='HH')
# Returns: {'x_min': ..., 'x_max': ..., 'y_min': ..., 'y_max': ...}
```

### 2. Add Margin

Add a margin around the footprint to ensure full coverage:

```python
margin_m = 5000  # 5 km margin
bbox_with_margin = {
    'x_min': bbox['x_min'] - margin_m,
    'x_max': bbox['x_max'] + margin_m,
    'y_min': bbox['y_min'] - margin_m,
    'y_max': bbox['y_max'] + margin_m,
}
```

### 3. Snap to Chunks

Snap the extended bbox to master grid chunks:

```python
from rift.grid import ANTARCTICA_GRID

snapped_bbox = ANTARCTICA_GRID.snap_bbox(bbox_with_margin, expand=True)
```

### 4. Compute Geogrid

Convert the snapped bbox to geogrid parameters:

```python
geogrid = ANTARCTICA_GRID.compute_geogrid_for_bbox(
    snapped_bbox,
    margin_m=0,  # Already added margin above
    snap_to_chunks=False  # Already snapped above
)
```

Or use the convenience method:

```python
geogrid = ANTARCTICA_GRID.compute_geogrid_for_granule(
    'granule/',
    polarization='HH',
    margin_m=5000,
    snap_to_chunks=True
)
```

### 5. Geocode

Use the geogrid for geocoding:

```bash
python src/geocode_biomass_custom_grid.py \
    --biomass-granule granule/ \
    --geogrid geogrid.json \
    --dem dem.tif \
    --output output.tif
```

## Validation

Validate that a geogrid is properly aligned:

```python
from rift.grid import ANTARCTICA_GRID

is_valid, message = ANTARCTICA_GRID.validate_geogrid(geogrid)
if is_valid:
    print("✓", message)
else:
    print("✗ Alignment issues:")
    print(message)
```

The validator checks:
1. EPSG matches (3031)
2. Pixel spacing matches (5m × 40m)
3. All boundaries align to chunk boundaries
4. Dimensions are multiples of 512

## Edge Cases

### Negative Coordinates

The grid works in all quadrants around the South Pole:

```python
# Southwest quadrant
bbox = {'x_min': -500000, 'x_max': -400000,
        'y_min': -600000, 'y_max': -500000}
snapped = ANTARCTICA_GRID.snap_bbox(bbox)
# All boundaries snap correctly to chunk boundaries
```

### Crossing the Origin

Bounding boxes that cross the origin (0, 0) are handled correctly:

```python
bbox = {'x_min': -50000, 'x_max': 50000,
        'y_min': -50000, 'y_max': 50000}
snapped = ANTARCTICA_GRID.snap_bbox(bbox)
# Snaps to: x_min=-51200, x_max=51200, etc.
```

### Small vs. Large Areas

The grid works for both small (single chunk) and large (thousands of chunks) areas:

```python
# Single chunk area
small = {'x_min': 100, 'x_max': 200, 'y_min': 100, 'y_max': 200}
geogrid_small = ANTARCTICA_GRID.compute_geogrid_for_bbox(small)
# Results in: 512 × 512 pixel grid

# Large area (hundreds of km)
large = {'x_min': -500000, 'x_max': 500000,
         'y_min': -500000, 'y_max': 500000}
geogrid_large = ANTARCTICA_GRID.compute_geogrid_for_bbox(large)
# Results in: 200,000 × 25,000 pixel grid
```

## Benefits of Chunk Alignment

### 1. Efficient Mosaicking

Multiple granules can be combined without reprocessing:

```bash
gdal_merge.py -o mosaic.tif granule1.tif granule2.tif granule3.tif
```

Since chunks align, GDAL can efficiently copy chunks without resampling.

### 2. Cloud-Optimized Access

Users can request specific chunks via HTTP range requests:

```python
import rasterio

with rasterio.open('s3://bucket/granule.tif') as src:
    # Only downloads the chunks intersecting this window
    window = src.window(x_min, y_min, x_max, y_max)
    data = src.read(1, window=window)
```

### 3. Time-Series Analysis

Stack multiple acquisitions without resampling:

```python
import rasterio

# All files have identical geotransforms and chunk boundaries
with rasterio.open('scene1.tif') as src1, \
     rasterio.open('scene2.tif') as src2, \
     rasterio.open('scene3.tif') as src3:
    
    # Read same spatial area from all scenes
    data1 = src1.read(1)
    data2 = src2.read(1)
    data3 = src3.read(1)
    
    # Pixel-to-pixel alignment guaranteed
    stack = np.stack([data1, data2, data3])
```

## References

- [Cloud-Optimized GeoTIFF](https://www.cogeo.org/)
- [GDAL COG Driver](https://gdal.org/drivers/raster/cog.html)
- [Antarctic Polar Stereographic (EPSG:3031)](https://epsg.io/3031)
