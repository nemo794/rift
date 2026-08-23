#!/usr/bin/env python3
"""
Tests for NISAR complex-domain regridding (rift.nisar.regrid).

Covers the three signal-processing guarantees:
1. Anti-alias downsampling reduces amplitude variance (multilook / speckle reduction).
2. Same-spacing placement is lossless and chunk-aligned (default 5×5 case).
3. Target geogrids snap to master-grid chunk boundaries.
"""

import sys
from pathlib import Path

import numpy as np
from rasterio.transform import Affine

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rift.grid import ANTARCTICA_GRID
from rift.nisar.regrid import (
    antialias_boxcar_complex,
    bounds_from_transform,
    compute_nisar_target_geogrid,
    decimation_factors,
    regrid_complex,
)


def _nisar_like_transform(x0=-1702077.5, y0=-130322.5, spacing=5.0):
    """NISAR-like north-up transform with pixel-corner origin (edges on the 5 m lattice)."""
    return Affine(spacing, 0.0, x0 - spacing / 2.0, 0.0, -spacing, y0 + spacing / 2.0)


def test_antialias_reduces_variance():
    rng = np.random.default_rng(42)
    arr = (rng.standard_normal((40, 40)) + 1j * rng.standard_normal((40, 40))).astype(np.complex64)
    decimated = antialias_boxcar_complex(arr, 4, 4)
    assert decimated.shape == (10, 10)
    # Multilook averaging reduces amplitude variance.
    assert np.abs(decimated).var() < np.abs(arr).var()


def test_antialias_beats_naive_decimation_variance():
    rng = np.random.default_rng(1)
    arr = (rng.standard_normal((40, 40)) + 1j * rng.standard_normal((40, 40))).astype(np.complex64)
    aa = np.abs(antialias_boxcar_complex(arr, 4, 4)).var()
    naive = np.abs(arr[::4, ::4]).var()
    # Boxcar (anti-aliased) result is smoother than naive subsampling.
    assert aa < naive


def test_decimation_factors():
    assert decimation_factors((5.0, 5.0), (5.0, 40.0)) == (8.0, 1.0)
    assert decimation_factors((5.0, 5.0), (5.0, 5.0)) == (1.0, 1.0)


def test_target_geogrid_chunk_aligned():
    tf = _nisar_like_transform()
    gg = compute_nisar_target_geogrid(tf, 100, 100, grid=ANTARCTICA_GRID)
    assert gg["x_posting"] == 5.0 and gg["y_posting"] == 5.0
    assert gg["x_min"] % ANTARCTICA_GRID.chunk_size_x == 0
    assert gg["y_min"] % ANTARCTICA_GRID.chunk_size_y == 0
    assert gg["width"] % 512 == 0
    assert gg["height"] % 512 == 0


def test_same_spacing_placement_lossless():
    rng = np.random.default_rng(7)
    arr = (rng.standard_normal((60, 60)) + 1j * rng.standard_normal((60, 60))).astype(np.complex64)
    tf = _nisar_like_transform()
    gg = compute_nisar_target_geogrid(tf, 60, 60, grid=ANTARCTICA_GRID)
    out = regrid_complex(arr, tf, gg, (5.0, 5.0), method="nearest")
    assert out.shape == (gg["height"], gg["width"])
    # Exactly 60*60 valid samples, amplitude sum preserved (windowed placement).
    assert np.sum(~np.isnan(out.real)) == 60 * 60
    assert np.isclose(np.nansum(np.abs(out)), np.sum(np.abs(arr)), rtol=1e-4)


def test_bounds_from_transform():
    tf = _nisar_like_transform()
    b = bounds_from_transform(tf, 100, 100)
    assert b["x_max"] > b["x_min"]
    assert b["y_max"] > b["y_min"]


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"✓ {name}")
    print("ALL NISAR REGRID TESTS PASSED")
