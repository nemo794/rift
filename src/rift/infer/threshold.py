#!/usr/bin/env python3
"""
Placeholder inference: binary threshold on an amplitude COG → binary-mask COG.

This is a stand-in for the trained ML model. It exists to lock the input/output contract
and grid alignment now: one amplitude COG in → one binary-mask COG out, on the identical
grid/transform. Pixels with amplitude strictly greater than ``threshold`` are marked 1;
all others (including no-data/NaN) are 0.

The real model will replace :func:`threshold_cog` with a proper inference call that
consumes the same COGs and emits masks on the same grid.

Usage:
    python -m rift.infer.threshold input_amp.tif output_mask.tif --threshold 0.5
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import rasterio

from rift.cogutil import base_profile, finalize_cog

MASK_NODATA = 255  # uint8 no-data sentinel; valid mask values are {0, 1}

# Color table so the mask is visible in GIS viewers (QGIS/ArcGIS). Without a palette a
# single-band Byte mask holding only {0, 1} renders under a min/max gray stretch, where 1
# maps to ~0.4% brightness — indistinguishable from the 0 background, so the layer looks
# empty ("won't load"). We render flagged pixels (1) opaque red and not-flagged pixels (0)
# black. NOTE: a TIFF color table is RGB-only — it cannot store per-entry alpha (GDAL
# forces every palette entry opaque on write), so transparency comes solely from the
# declared no-data value (MASK_NODATA), which QGIS honors. Invalid/fill pixels are written
# as MASK_NODATA (see threshold_cog) so the geocoding-fill border renders transparent
# rather than as an opaque black block.
MASK_COLORMAP = {
    0: (0, 0, 0, 255),       # valid, not flagged → black
    1: (230, 30, 30, 255),   # flagged → red
    MASK_NODATA: (0, 0, 0, 255),  # nodata → color irrelevant; transparency via nodata tag
}


def threshold_cog(input_cog: Path, output_cog: Path, threshold: float,
                  tile_size: int = 512) -> Path:
    """
    Apply a binary amplitude threshold to a COG, writing a uint8 mask COG.

    Args:
        input_cog: Input amplitude COG (float, band 1)
        output_cog: Output binary-mask COG path
        threshold: Amplitude threshold; ``amp > threshold`` → 1, else 0
        tile_size: Processing block size (default 512, matches COG blocks)

    Returns:
        Path: The output mask COG path
    """
    input_cog = Path(input_cog)
    output_cog = Path(output_cog)

    with rasterio.open(input_cog) as src:
        profile = base_profile(
            width=src.width, height=src.height, epsg=src.crs.to_epsg(),
            transform=src.transform, dtype="uint8", count=1,
            nodata=MASK_NODATA, blocksize=tile_size, predictor=2,
        )
        temp_file = output_cog.with_suffix(".temp.tif")

        with rasterio.open(temp_file, "w", **profile) as dst:
            # Stream by blocks to stay memory-safe on large rasters.
            for _, window in src.block_windows(1):
                amp = src.read(1, window=window)
                valid = np.isfinite(amp)
                # Invalid/fill pixels (NaN geocoding border) → MASK_NODATA so they render
                # transparent; valid pixels are 0 (below/at threshold) or 1 (above).
                mask = np.full(amp.shape, MASK_NODATA, dtype=np.uint8)
                mask[valid] = 0
                mask[valid & (amp > threshold)] = 1
                dst.write(mask, 1, window=window)

            dst.set_band_description(1, "Binary mask (placeholder threshold)")
            # Palette so the mask renders as a visible overlay instead of a near-black
            # layer under GIS min/max stretch (see MASK_COLORMAP).
            dst.write_colormap(1, MASK_COLORMAP)
            dst.update_tags(1, BAND_TYPE="binary_mask", THRESHOLD=str(threshold))
            dst.update_tags(
                SOURCE_FILE=input_cog.name,
                PROCESSING="Placeholder inference: binary amplitude threshold",
                THRESHOLD=str(threshold),
                MASK_VALUES="1=above threshold, 0=at/below threshold, 255=nodata/invalid",
            )

    # NEAREST overviews: the mask is categorical/paletted, so averaging indices would
    # produce meaningless colors and wash out the sparse flagged pixels at zoom-out.
    finalize_cog(temp_file, output_cog, predictor=2, overview_resampling="NEAREST")
    return output_cog


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("input", type=Path, help="Input amplitude COG")
    parser.add_argument("output", type=Path, help="Output binary-mask COG")
    parser.add_argument("--threshold", type=float, required=True,
                        help="Amplitude threshold (amp > threshold → 1)")
    parser.add_argument("--tile-size", type=int, default=512)
    args = parser.parse_args()

    if not args.input.exists():
        print(f"ERROR: Input not found: {args.input}")
        return 1

    out = threshold_cog(args.input, args.output, args.threshold, args.tile_size)
    print(f"✓ Wrote mask COG: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
