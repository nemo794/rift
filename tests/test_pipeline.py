#!/usr/bin/env python3
"""
Tests for the end-to-end pipeline wiring (rift.pipeline).

Uses monkeypatching to stub the heavy sensor steps (ISCE3 geocode / HDF5 extract) so we
can verify orchestration behavior without real granules:
  * config JSON is written to output_dir
  * keep_intermediates toggles whether amplitude COGs remain in output_dir
  * masks are always produced
"""

import sys
import tempfile
from pathlib import Path

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import Affine

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import rift.pipeline as pipeline


def _make_amp_cog(path):
    """Write a tiny valid amplitude COG-like GeoTIFF."""
    data = np.array([[0.1, 0.9], [1.5, np.nan]], dtype=np.float32)
    profile = {
        "driver": "GTiff", "dtype": "float32", "width": 2, "height": 2, "count": 1,
        "crs": CRS.from_epsg(3031), "transform": Affine(5, 0, 0, 0, -5, 0),
        "nodata": np.nan, "tiled": True, "blockxsize": 256, "blockysize": 256,
    }
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)


def _stub_nisar_to_cogs(gslc, output_dir, **kwargs):
    out = Path(output_dir) / "STUB_HH_amp.tif"
    _make_amp_cog(out)
    return [out]


def test_nisar_e2e_deletes_intermediates_by_default(monkeypatch):
    monkeypatch.setattr(pipeline, "nisar_to_cogs", _stub_nisar_to_cogs)
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        result = pipeline.run_nisar_end_to_end(
            Path("dummy.h5"), d, threshold=0.5, keep_intermediates=False, pols=["HH"]
        )
        # Config written.
        assert (d / "nisar_e2e_config.json").exists()
        assert result["config"].name == "nisar_e2e_config.json"
        # Masks produced.
        assert len(result["masks"]) == 1
        assert result["masks"][0].exists()
        # Amplitude COGs deleted (none kept, none left as *_amp.tif in output).
        assert result["amplitudes"] == []
        assert not list(d.glob("*_amp.tif"))


def test_nisar_e2e_keeps_intermediates(monkeypatch):
    monkeypatch.setattr(pipeline, "nisar_to_cogs", _stub_nisar_to_cogs)
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        result = pipeline.run_nisar_end_to_end(
            Path("dummy.h5"), d, threshold=0.5, keep_intermediates=True, pols=["HH"]
        )
        assert len(result["amplitudes"]) == 1
        assert result["amplitudes"][0].exists()
        assert result["amplitudes"][0].parent == d
        assert len(result["masks"]) == 1


def test_config_records_resolved_params(monkeypatch):
    monkeypatch.setattr(pipeline, "nisar_to_cogs", _stub_nisar_to_cogs)
    import json
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        pipeline.run_nisar_end_to_end(Path("g.h5"), d, x_spacing=5, y_spacing=40,
                                      threshold=0.3, keep_intermediates=False, pols=["HH"])
        cfg = json.loads((d / "nisar_e2e_config.json").read_text())
        assert cfg["workflow"] == "nisar-e2e"
        assert cfg["y_spacing"] == 40
        assert cfg["threshold"] == 0.3


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
