#!/usr/bin/env python3
"""
Tests for the amplitude/phase COG output behavior (rift.biomass.geocode.write_biomass_cog).

rift defaults to writing amplitude and phase as *separate* single-band COGs, mirroring the
source L1A abs/phase measurement layout:
    * <output>       amplitude (linear, float32)
    * <output>_phs   phase (radians -π..π, float32) — only when phase_file is given

These tests write real COGs from a tiny synthetic complex array (no granule / ISCE3
needed) and verify which files are produced, their band content, and co-registration.
"""

import sys
import tempfile
from datetime import datetime
from pathlib import Path

import numpy as np
import rasterio

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from rift.biomass.geocode import write_biomass_cog


def _grid_params():
    """Minimal geogrid dict matching what write_biomass_cog consumes."""
    return {
        "x_min": 100000.0, "y_max": -400000.0,
        "x_posting": 5.0, "y_posting": 5.0,
        "width": 4, "height": 3, "epsg": 3031,
    }


def _complex_data(grid):
    """A small complex array with a known amplitude/phase and one invalid (NaN) pixel."""
    data = np.array([
        [1 + 0j, 0 + 1j, 1 + 1j, 2 + 0j],
        [0 - 1j, 3 + 4j, 1 - 1j, 0.5 + 0j],
        [np.nan + 1j * np.nan, 1 + 0j, 0 + 2j, 1 + 1j],
    ], dtype=np.complex64)
    assert data.shape == (grid["height"], grid["width"])
    return data


def _metadata():
    return {"POLARIZATION": "HH", "PROCESSING": "test"}


def test_writes_both_amp_and_phase_by_default():
    grid = _grid_params()
    data = _complex_data(grid)
    acq = datetime(2025, 11, 26, 13, 55, 34)

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        amp_path = d / "scene_HH_amp.tif"
        phase_path = d / "scene_HH_phs.tif"

        written = write_biomass_cog(amp_path, data, grid, acq, "HH", _metadata(),
                                    phase_file=phase_path)

        # Both files produced and returned (amplitude first).
        assert written == [amp_path, phase_path]
        assert amp_path.exists()
        assert phase_path.exists()

        # Amplitude: values match |z|, band tagged as amplitude, grid preserved.
        with rasterio.open(amp_path) as src:
            assert src.count == 1
            assert src.dtypes[0] == "float32"
            assert src.tags(1).get("BAND_TYPE") == "amplitude"
            amp = src.read(1)
            expected = np.abs(data)
            valid = np.isfinite(expected)
            assert np.allclose(amp[valid], expected[valid], atol=1e-5)
            assert np.isnan(amp[~valid]).all()

        # Phase: values match angle(z) in radians, band tagged as phase, same grid.
        with rasterio.open(phase_path) as src:
            assert src.count == 1
            assert src.dtypes[0] == "float32"
            assert src.tags(1).get("BAND_TYPE") == "phase"
            assert src.tags(1).get("UNITS") == "radians"
            phase = src.read(1)
            expected = np.angle(data)
            valid = np.isfinite(np.abs(data))
            assert np.allclose(phase[valid], expected[valid], atol=1e-5)
            pv = phase[valid]
            assert pv.min() >= -np.pi - 1e-4 and pv.max() <= np.pi + 1e-4

        # Amplitude and phase are co-registered (identical grid/transform/crs).
        with rasterio.open(amp_path) as a, rasterio.open(phase_path) as p:
            assert (a.width, a.height) == (p.width, p.height)
            assert a.transform == p.transform
            assert a.crs == p.crs


def test_amp_only_writes_no_phase():
    grid = _grid_params()
    data = _complex_data(grid)
    acq = datetime(2025, 11, 26, 13, 55, 34)

    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        amp_path = d / "scene_HH_amp.tif"
        phase_path = d / "scene_HH_phs.tif"

        # phase_file=None => amplitude only (the --amp-only path).
        written = write_biomass_cog(amp_path, data, grid, acq, "HH", _metadata(),
                                    phase_file=None)

        assert written == [amp_path]
        assert amp_path.exists()
        assert not phase_path.exists()
        assert not list(d.glob("*_phs.tif"))


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
