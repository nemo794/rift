#!/usr/bin/env python3
"""
Tests for the placeholder inference (rift.infer.threshold).

Covers threshold correctness (including NaN handling) and grid/transform preservation.
"""

import sys
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import Affine

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rift.infer.threshold import threshold_cog, MASK_NODATA


def _write_amp(path, data, transform, epsg=3031):
    profile = {
        "driver": "GTiff", "dtype": "float32", "width": data.shape[1],
        "height": data.shape[0], "count": 1, "crs": CRS.from_epsg(epsg),
        "transform": transform, "nodata": np.nan, "tiled": True,
        "blockxsize": 256, "blockysize": 256,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)


def test_threshold_correctness_and_grid_preserved():
    amp = np.array([[0.0, 0.5, 1.0],
                    [2.0, np.nan, 0.2],
                    [5.0, 0.49, 0.51]], dtype=np.float32)
    transform = Affine(5.0, 0.0, 100000.0, 0.0, -5.0, -400000.0)

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        amp_path = d / "amp.tif"
        mask_path = d / "mask.tif"
        _write_amp(amp_path, amp, transform)

        threshold_cog(amp_path, mask_path, threshold=0.5)

        with rasterio.open(mask_path) as src:
            mask = src.read(1)
            # Grid/transform preserved.
            assert src.transform == transform
            assert src.crs.to_epsg() == 3031
            assert src.width == 3 and src.height == 3
            assert src.dtypes[0] == "uint8"
            assert src.nodata == MASK_NODATA

    # amp > 0.5 → 1; NaN → 0; exactly 0.5 → 0.
    expected = np.array([[0, 0, 1],
                         [1, 0, 0],
                         [1, 0, 1]], dtype=np.uint8)
    assert np.array_equal(mask, expected)


if __name__ == "__main__":
    test_threshold_correctness_and_grid_preserved()
    print("✓ test_threshold_correctness_and_grid_preserved")
    print("ALL INFER TESTS PASSED")
