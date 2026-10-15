#!/usr/bin/env python3
"""Derive per-polarization intensity (a.k.a. power) COGs from geocoded amplitude COGs.

Both the ``nisar2cog`` and ``biomass2cog`` pipelines emit a per-polarization amplitude
COG named ``*_<POL>_amp.tif``. Intensity (linear power) is simply ``amp**2``, so this
module reads an amplitude COG block-by-block (to keep memory modest), squares it, and
writes a co-registered ``*_<POL>_intensity.tif`` COG.

The ``*_<POL>_intensity.tif`` naming is required by the downstream BIOMASS crevasse model
(``nisar-crevasse``'s ``crevasse.biomass.run_granule._granule_paths`` globs
``*_<POL>_intensity.tif`` for each of HH/HV/VH/VV), so this suffix is a hard contract, not
a cosmetic choice.

This logic previously lived in ``scripts/make_pwr_cogs.py``; it now lives here so the
``rift`` pipelines can emit intensity COGs in-process via the ``--products`` flag, and the
script is a thin wrapper around :func:`make_intensity_cogs`.
"""

from __future__ import annotations

import glob
import os
from pathlib import Path
from typing import List, Optional, Sequence

import numpy as np
import rasterio

from rift.cogutil import base_profile, finalize_cog

# The four BIOMASS/NISAR polarizations the directory-level helper looks for.
POLS = ["HH", "HV", "VH", "VV"]


def amp_to_intensity_cog(amp_path, out_path=None) -> Path:
    """Read one amplitude COG, square it block-wise, and write an intensity COG.

    Args:
        amp_path: Path to a ``*_<POL>_amp.tif`` amplitude COG.
        out_path: Destination intensity COG. Defaults to the input path with the
            ``_amp.tif`` suffix replaced by ``_intensity.tif``.

    Returns:
        Path: The written intensity COG.
    """
    amp_path = Path(amp_path)
    if out_path is None:
        out_path = amp_path.with_name(amp_path.name.replace("_amp.tif", "_intensity.tif"))
    out_path = Path(out_path)
    temp_path = out_path.with_suffix(".temp.tif")
    print(f"  {amp_path.name} -> {out_path.name}")

    with rasterio.open(amp_path) as src:
        profile = base_profile(
            width=src.width,
            height=src.height,
            epsg=src.crs.to_epsg(),
            transform=src.transform,
            dtype="float32",
            nodata=np.nan,
        )
        with rasterio.open(temp_path, "w", **profile) as dst:
            # Iterate over the source's native block windows to bound memory use.
            for _, window in src.block_windows(1):
                amp = src.read(1, window=window)
                # intensity = |complex|**2 = amp**2 ; NaNs propagate as nodata.
                intensity = np.square(amp, dtype=np.float32)
                dst.write(intensity, 1, window=window)

    # Convert the tiled temp GeoTIFF to a proper COG (builds overviews); float predictor.
    finalize_cog(temp_path, out_path, predictor=3, overview_resampling="AVERAGE")
    return out_path


def _amp_path(data_dir: Path, pol: str) -> Optional[Path]:
    """Return the single ``*_<POL>_amp.tif`` in ``data_dir``, or None if absent."""
    matches = glob.glob(os.path.join(data_dir, f"*_{pol}_amp.tif"))
    if len(matches) > 1:
        raise RuntimeError(f"expected <=1 {pol}_amp.tif, found {matches}")
    return Path(matches[0]) if matches else None


def make_intensity_cogs(data_dir, output_dir=None,
                        pols: Sequence[str] = POLS) -> List[Path]:
    """Derive ``*_<POL>_intensity.tif`` for each amplitude COG found in ``data_dir``.

    Args:
        data_dir: Directory containing ``*_<POL>_amp.tif`` COGs.
        output_dir: Output directory for the intensity COGs (default: same as ``data_dir``).
        pols: Polarizations to look for (default: HH/HV/VH/VV).

    Returns:
        List of paths to the intensity COGs written.
    """
    data_dir = Path(data_dir).resolve()
    out_dir = Path(output_dir).resolve() if output_dir else data_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Creating intensity COGs from amplitude COGs in {data_dir}")
    written: List[Path] = []
    for pol in pols:
        src_path = _amp_path(data_dir, pol)
        if src_path is None:
            print(f"[{pol}] no *_{pol}_amp.tif found, skipping")
            continue
        print(f"[{pol}]")
        out_path = out_dir / src_path.name.replace("_amp.tif", "_intensity.tif")
        written.append(amp_to_intensity_cog(src_path, out_path))

    print(f"Done: {len(written)} intensity COG(s) written.")
    return written
