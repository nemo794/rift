#!/usr/bin/env python3
"""
Shared Cloud-Optimized GeoTIFF (COG) helpers.

Both the BIOMASS geocoder and the NISAR extractor write a temporary tiled GeoTIFF and
then convert it to a COG with identical ``gdal_translate`` options. This module holds
that logic in one place so the COG creation options (block size, compression, overviews)
stay consistent across every product ``rift`` emits.

Typical usage (whole array in memory)::

    profile = base_profile(width, height, epsg, transform, dtype="float32",
                           nodata=np.nan, blocksize=512)
    write_cog(output_path, {1: (amplitude, band_meta)}, profile, global_meta=meta)

For streaming (tile-by-tile) writes, use ``open_temp`` / ``finalize_cog`` directly.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import rasterio
from rasterio.crs import CRS

# COG creation options shared by every product rift writes. PREDICTOR is dtype-dependent
# (3 = floating point, 2 = horizontal/integer) and OVERVIEW_RESAMPLING is data-dependent
# (AVERAGE for continuous float rasters, NEAREST for categorical/paletted masks), so both
# are appended per-call by _cog_options(); the COG driver uses LEVEL (not ZLEVEL) for the
# DEFLATE level.
_COG_BASE_OPTIONS = [
    "-of", "COG",
    "-co", "BLOCKSIZE=512",
    "-co", "COMPRESS=DEFLATE",
    "-co", "LEVEL=1",
    "-co", "NUM_THREADS=ALL_CPUS",
    "-co", "BIGTIFF=YES",
]


def _cog_options(predictor: int, overview_resampling: str = "AVERAGE") -> list:
    """Full gdal_translate COG options with a dtype-appropriate PREDICTOR/resampling."""
    return [
        *_COG_BASE_OPTIONS,
        "-co", f"OVERVIEW_RESAMPLING={overview_resampling}",
        "-co", f"PREDICTOR={predictor}",
    ]


def base_profile(
    width: int,
    height: int,
    epsg: int,
    transform,
    *,
    dtype: str = "float32",
    count: int = 1,
    nodata=np.nan,
    blocksize: int = 512,
    predictor: int = 3,
) -> dict:
    """
    Build a rasterio profile for the temporary tiled GeoTIFF.

    Args:
        width, height: Raster dimensions in pixels
        epsg: Projection EPSG code
        transform: Affine transform (north-up)
        dtype: Band data type (e.g. "float32", "uint8")
        count: Number of bands
        nodata: No-data value (np.nan for float amplitude, an int for masks)
        blocksize: Internal tiling block size (matches COG BLOCKSIZE)
        predictor: DEFLATE predictor for the *temporary* file (3 = float, 2 = int)

    Returns:
        dict: rasterio profile suitable for ``rasterio.open(..., 'w', **profile)``
    """
    return {
        "driver": "GTiff",
        "dtype": dtype,
        "width": width,
        "height": height,
        "count": count,
        "crs": CRS.from_epsg(epsg),
        "transform": transform,
        "nodata": nodata,
        "tiled": True,
        "blockxsize": blocksize,
        "blockysize": blocksize,
        "compress": "DEFLATE",
        "predictor": predictor,
        "BIGTIFF": "YES",
    }


def finalize_cog(temp_file: Path, output_file: Path, *, predictor: int = 3,
                 overview_resampling: str = "AVERAGE", cleanup: bool = True) -> Path:
    """
    Convert a temporary GeoTIFF to a COG via ``gdal_translate`` and remove the temp file.

    Args:
        temp_file: Path to the temporary tiled GeoTIFF
        output_file: Destination COG path
        predictor: DEFLATE predictor — 3 for float rasters, 2 for integer (e.g. masks)
        overview_resampling: Overview downsampling method — ``AVERAGE`` for continuous
            float rasters (amplitude), ``NEAREST`` for categorical/paletted rasters (masks).
            Averaging palette indices or a sparse binary mask washes it out at zoom-out.
        cleanup: Remove the temporary file on success (default True)

    Returns:
        Path: The output COG path

    Raises:
        RuntimeError: If ``gdal_translate`` fails
    """
    temp_file = Path(temp_file)
    output_file = Path(output_file)

    cmd = ["gdal_translate", str(temp_file), str(output_file),
           *_cog_options(predictor, overview_resampling)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gdal_translate failed: {result.stderr}")

    if cleanup and temp_file.exists():
        temp_file.unlink()

    return output_file


def write_cog(
    output_file: Path,
    bands: Dict[int, Tuple[np.ndarray, Optional[dict]]],
    profile: dict,
    *,
    band_descriptions: Optional[Dict[int, str]] = None,
    global_meta: Optional[dict] = None,
) -> Path:
    """
    Write an in-memory multi-band array to a COG.

    Args:
        output_file: Destination COG path
        bands: Mapping ``{band_index: (array, band_tags_or_None)}`` (1-indexed bands)
        profile: rasterio profile from :func:`base_profile` (``count`` must match)
        band_descriptions: Optional ``{band_index: description}`` set via
            ``set_band_description``
        global_meta: Optional dataset-level tag dict

    Returns:
        Path: The output COG path
    """
    output_file = Path(output_file)
    temp_file = output_file.with_suffix(".temp.tif")

    with rasterio.open(temp_file, "w", **profile) as dst:
        for band_idx, (array, band_tags) in bands.items():
            dst.write(array, band_idx)
            if band_descriptions and band_idx in band_descriptions:
                dst.set_band_description(band_idx, band_descriptions[band_idx])
            if band_tags:
                dst.update_tags(band_idx, **band_tags)
        if global_meta:
            dst.update_tags(**global_meta)

    predictor = int(profile.get("predictor", 3))
    return finalize_cog(temp_file, output_file, predictor=predictor)
