#!/usr/bin/env python3
"""
Tests for NISAR master-grid placement (rift.nisar).

The NISAR path is placement-only: no resampling, no interpolation, no subpixel shift.
These tests cover the remaining guarantees:
1. Target geogrids snap to master-grid chunk boundaries.
2. An aligned granule places losslessly at an integer pixel offset.
3. A fractionally-offset granule is rejected (ValueError) rather than resampled.
"""

import sys
from pathlib import Path

import numpy as np
from rasterio.transform import Affine

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

from rift.grid import ANTARCTICA_GRID
from rift.nisar.extract import process_single_polarization
from rift.nisar.regrid import (
    bounds_from_transform,
    compute_nisar_target_geogrid,
    geogrid_transform,
    _is_integer,
)


def _nisar_like_transform(x0=-1702077.5, y0=-130322.5, spacing=5.0):
    """NISAR-like north-up transform with pixel-corner origin (edges on the 5 m lattice)."""
    return Affine(spacing, 0.0, x0 - spacing / 2.0, 0.0, -spacing, y0 + spacing / 2.0)


def _pixel_offset(transform, geogrid):
    """Integer-valued (row, col) offset of the source origin within the target canvas."""
    col_off = (transform.c - geogrid["x_min"]) / geogrid["x_posting"]
    row_off = (geogrid["y_max"] - transform.f) / geogrid["y_posting"]
    return row_off, col_off


def test_target_geogrid_chunk_aligned():
    tf = _nisar_like_transform()
    gg = compute_nisar_target_geogrid(tf, 100, 100, grid=ANTARCTICA_GRID)
    assert gg["x_posting"] == 5.0 and gg["y_posting"] == 5.0
    assert gg["x_min"] % ANTARCTICA_GRID.chunk_size_x == 0
    assert gg["y_min"] % ANTARCTICA_GRID.chunk_size_y == 0
    assert gg["width"] % 512 == 0
    assert gg["height"] % 512 == 0


def test_aligned_granule_has_integer_offset():
    """An on-lattice granule places at an integer pixel offset — lossless placement."""
    tf = _nisar_like_transform()
    gg = compute_nisar_target_geogrid(tf, 60, 60, grid=ANTARCTICA_GRID)
    row_off, col_off = _pixel_offset(tf, gg)
    assert _is_integer(row_off) and _is_integer(col_off)
    # The whole native array fits inside the (expanded, chunk-snapped) canvas.
    assert int(round(row_off)) >= 0 and int(round(col_off)) >= 0
    assert int(round(row_off)) + 60 <= gg["height"]
    assert int(round(col_off)) + 60 <= gg["width"]


def test_fractional_offset_detected():
    """A half-pixel-shifted granule yields a non-integer offset (must be rejected)."""
    tf = _nisar_like_transform()
    # Shift the origin by 2.5 m (half a pixel) off the 5 m lattice.
    shifted = Affine(tf.a, 0.0, tf.c + 2.5, 0.0, tf.e, tf.f)
    gg = compute_nisar_target_geogrid(shifted, 60, 60, grid=ANTARCTICA_GRID)
    row_off, col_off = _pixel_offset(shifted, gg)
    assert not (_is_integer(row_off) and _is_integer(col_off))


def test_process_raises_on_fractional_offset(tmp_path):
    """process_single_polarization must reject a misaligned granule before any resampling."""
    shifted = Affine(5.0, 0.0, -1702080.0 + 2.5, 0.0, -5.0, -130320.0 + 2.5)
    geo_info = {
        "epsg": 3031,
        "transform": shifted,
        "width": 60,
        "height": 60,
        "x_spacing": 5.0,
        "y_spacing": -5.0,
    }
    with pytest.raises(ValueError, match="does not align to the master grid"):
        process_single_polarization(
            "dummy.h5", "HH", geo_info, tmp_path / "out_HH_amp.tif",
        )


def test_geogrid_transform_roundtrip():
    tf = _nisar_like_transform()
    gg = compute_nisar_target_geogrid(tf, 60, 60, grid=ANTARCTICA_GRID)
    target_tf = geogrid_transform(gg)
    assert target_tf.a == gg["x_posting"]
    assert target_tf.e == -gg["y_posting"]
    assert target_tf.c == gg["x_min"]
    assert target_tf.f == gg["y_max"]


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
    print("ALL NISAR PLACEMENT TESTS PASSED")
