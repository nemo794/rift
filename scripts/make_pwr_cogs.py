#!/usr/bin/env python3
"""Create per-polarization intensity (a.k.a. power) COGs from geocoded amplitude COGs.

Both the ``nisar2cog`` and ``biomass2cog`` pipelines emit a per-polarization amplitude
COG named ``*_<POL>_amp.tif``. Intensity (linear power) is simply ``amp**2``, so this
script reads each amplitude COG block-by-block (to keep memory modest), squares it, and
writes a co-registered ``*_<POL>_intensity.tif`` COG alongside the input.

The ``*_<POL>_intensity.tif`` naming is required by the downstream BIOMASS crevasse model
(``nisar-crevasse``'s ``crevasse.biomass.run_granule._granule_paths`` globs
``*_<POL>_intensity.tif`` for each of HH/HV/VH/VV), so this suffix is a hard contract, not
a cosmetic choice.

Phase COGs (``*_<POL>_phs.tif``) are not needed for intensity and are ignored.

Usage::

    python scripts/make_pwr_cogs.py <data_dir> [--output-dir DIR]

By default the intensity COGs are written to the same directory as their source amplitude
COGs. Existing intensity COGs are always overwritten.
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
from pathlib import Path

import numpy as np
import rasterio

# Make ``rift`` importable when run from a source checkout without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rift.cogutil import base_profile, finalize_cog  # noqa: E402

POLS = ["HH", "HV", "VH", "VV"]


def amp_path(data_dir: Path, pol: str):
    """Return the single ``*_<POL>_amp.tif`` in ``data_dir``, or None if absent."""
    matches = glob.glob(os.path.join(data_dir, f"*_{pol}_amp.tif"))
    if len(matches) > 1:
        raise RuntimeError(f"expected <=1 {pol}_amp.tif, found {matches}")
    return Path(matches[0]) if matches else None


def build_one(src_path: Path, out_dir: Path) -> Path:
    """Read one amplitude COG, square it block-wise, and write an intensity COG."""
    out_path = out_dir / src_path.name.replace("_amp.tif", "_intensity.tif")
    temp_path = out_path.with_suffix(".temp.tif")
    print(f"  {src_path.name} -> {out_path.name}")

    with rasterio.open(src_path) as src:
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


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "data_dir",
        type=Path,
        help="Directory containing *_<POL>_amp.tif COGs",
    )
    ap.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for the intensity COGs (default: same as each input)",
    )
    args = ap.parse_args()

    data_dir = args.data_dir.resolve()
    if not data_dir.is_dir():
        print(f"ERROR: not a directory: {data_dir}", file=sys.stderr)
        return 1

    out_dir = args.output_dir.resolve() if args.output_dir else data_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Creating intensity COGs from amplitude COGs in {data_dir}")
    n = 0
    for pol in POLS:
        src_path = amp_path(data_dir, pol)
        if src_path is None:
            print(f"[{pol}] no *_{pol}_amp.tif found, skipping")
            continue
        print(f"[{pol}]")
        build_one(src_path, out_dir)
        n += 1

    if n == 0:
        print("No amplitude COGs found.", file=sys.stderr)
        return 1
    print(f"Done: {n} intensity COG(s) written.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
