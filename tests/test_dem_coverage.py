#!/usr/bin/env python3
"""
Tests for the fail-early DEM coverage check (rift.biomass.geocode.check_dem_covers_grid).

Covers: a DEM that fully covers the grid (passes), a DEM whose extent does not contain the
grid (raises), and a DEM that contains the grid spatially but is all-nodata over it
(raises — the real failure mode that a bbox-only check would miss).

Imports the checker from a submodule that does not require isce3/biomass_reader at import
time, so these run without the heavy SAR stack.
"""

import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_origin

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

pytest.importorskip("rasterio")

# check_dem_covers_grid lives in geocode.py which imports isce3/biomass_reader at module
# load; skip the whole module if those aren't installed in this environment.
geocode = pytest.importorskip("rift.biomass.geocode")
check_dem_covers_grid = geocode.check_dem_covers_grid
DemCoverageError = geocode.DemCoverageError


# A small EPSG:3031 grid.
GRID = {
    "epsg": 3031,
    "x_min": 0.0, "x_max": 2560.0,
    "y_min": 0.0, "y_max": 2560.0,
    "width": 512, "height": 512,
    "x_posting": 5.0, "y_posting": 5.0,
}


def _write_dem(path, *, x0, y0, nx, ny, res, fill, nodata=np.nan, epsg=3031):
    transform = from_origin(x0, y0, res, res)  # y0 is the top edge
    data = np.full((ny, nx), fill, dtype=np.float32)
    profile = {
        "driver": "GTiff", "dtype": "float32", "width": nx, "height": ny, "count": 1,
        "crs": CRS.from_epsg(epsg), "transform": transform, "nodata": nodata,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)


def test_dem_fully_covers_grid_passes():
    with tempfile.TemporaryDirectory() as d:
        dem = Path(d) / "cover.tif"
        # DEM spans well beyond the grid, valid data everywhere.
        _write_dem(dem, x0=-5000, y0=7560, nx=3000, ny=3000, res=5, fill=100.0)
        assert check_dem_covers_grid(dem, GRID) is True


def test_dem_extent_too_small_raises():
    with tempfile.TemporaryDirectory() as d:
        dem = Path(d) / "small.tif"
        # DEM only covers a corner of the grid.
        _write_dem(dem, x0=0, y0=1280, nx=256, ny=256, res=5, fill=100.0)
        with pytest.raises(DemCoverageError):
            check_dem_covers_grid(dem, GRID)


def test_dem_all_nodata_over_grid_raises():
    with tempfile.TemporaryDirectory() as d:
        dem = Path(d) / "nodata.tif"
        # Extent contains the grid, but every value is nodata (NaN).
        _write_dem(dem, x0=-5000, y0=7560, nx=3000, ny=3000, res=5, fill=np.nan)
        with pytest.raises(DemCoverageError) as exc:
            check_dem_covers_grid(dem, GRID)
        assert "valid elevation data" in str(exc.value)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
