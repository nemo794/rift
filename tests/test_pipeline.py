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
        pipeline.run_nisar_end_to_end(Path("g.h5"), d,
                                      threshold=0.3, keep_intermediates=False, pols=["HH"])
        cfg = json.loads((d / "nisar_e2e_config.json").read_text())
        assert cfg["workflow"] == "nisar-e2e"
        # NISAR always uses the shared 5×5 m master grid (no spacing options).
        assert cfg["x_spacing"] == 5 and cfg["y_spacing"] == 5
        assert cfg["threshold"] == 0.3
        # The resolved config records the products selection (replacing the old amp_only).
        assert cfg["products"] == ["amp", "phs"]
        assert "amp_only" not in cfg


# --------------------------------------------------------------------------------------
# Product selection
# --------------------------------------------------------------------------------------

def test_normalize_products_default_and_dedup():
    assert pipeline._normalize_products(None) == ["amp", "phs"]
    # Case-insensitive, deduped, re-ordered to canonical amp→phs→intensity.
    assert pipeline._normalize_products(["INTENSITY", "amp", "amp"]) == ["amp", "intensity"]


def test_normalize_products_rejects_empty_and_unknown():
    import pytest
    with pytest.raises(ValueError):
        pipeline._normalize_products([])
    with pytest.raises(ValueError):
        pipeline._normalize_products(["", "  "])
    with pytest.raises(ValueError):
        pipeline._normalize_products(["power"])  # typo must fail loudly


def test_select_products_intensity_only_drops_amp():
    """products=[intensity] derives the intensity COG and removes the amp COG."""
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        amp = d / "G_HH_amp.tif"
        _make_amp_cog(amp)
        kept = pipeline._select_products([amp], amp, ["intensity"])
        names = sorted(p.name for p in kept)
        assert names == ["G_HH_intensity.tif"]
        assert (d / "G_HH_intensity.tif").exists()
        assert not amp.exists()  # amp not requested → removed


def test_select_products_amp_and_intensity_kept_in_order():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        amp = d / "G_HH_amp.tif"
        _make_amp_cog(amp)
        kept = pipeline._select_products([amp], amp, ["amp", "intensity"])
        assert [p.name for p in kept] == ["G_HH_amp.tif", "G_HH_intensity.tif"]
        assert amp.exists()


def test_e2e_guard_requires_inference_product(monkeypatch):
    """Each e2e raises if its inference product is dropped from the selection."""
    import pytest
    monkeypatch.setattr(pipeline, "nisar_to_cogs", _stub_nisar_to_cogs)
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        # NISAR e2e needs amp; a phs-only selection is rejected before any work.
        with pytest.raises(ValueError, match="amp"):
            pipeline.run_nisar_end_to_end(Path("dummy.h5"), d, pols=["HH"],
                                          products=["phs"])


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
