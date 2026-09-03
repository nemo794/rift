#!/usr/bin/env python3
"""
Place NISAR GSLC data onto the Antarctica master grid.

NISAR L2 GSLC products are already in EPSG:3031 at 5×5 m posting, and their pixel edges
already fall on integer multiples of 5 m from the origin — which is exactly the master-grid
lattice. So putting a NISAR granule on the master grid is a **lossless windowed placement**:
native complex samples are copied into a chunk-aligned canvas at an integer pixel offset,
with the fill border padded so the extent is a whole number of 512×512 chunks. There is
**no resampling, no interpolation, and no subpixel shift** (see docs/GRID_RESAMPLING_DECISION.md,
docs/NISAR_WORKFLOW.md).

Detection rule: masking and placement happen on the **complex** samples; the caller takes
amplitude ``|·|`` last (detecting before placement would corrupt speckle statistics).

If a granule's origin does not land on an integer master-grid pixel offset, that is a hard
error — the extractor raises rather than silently resampling. This module deliberately
contains no interpolation code so no subpixel-shift path can exist.
"""

from __future__ import annotations

from typing import Dict

import numpy as np
from rasterio.transform import Affine

from rift.grid import ANTARCTICA_GRID, AntarcticaGrid


def bounds_from_transform(transform: Affine, width: int, height: int) -> Dict[str, float]:
    """
    Compute the pixel-edge bounding box (EPSG:3031) from a north-up affine transform.

    Args:
        transform: Affine transform with pixel-corner origin (north-up: transform.e < 0)
        width, height: Raster size in pixels

    Returns:
        dict: {x_min, x_max, y_min, y_max} at pixel edges
    """
    x_min = transform.c
    y_max = transform.f
    x_max = x_min + width * transform.a
    y_min = y_max + height * transform.e  # transform.e is negative
    return {"x_min": x_min, "x_max": x_max, "y_min": y_min, "y_max": y_max}


def compute_nisar_target_geogrid(
    transform: Affine,
    width: int,
    height: int,
    grid: AntarcticaGrid = ANTARCTICA_GRID,
) -> Dict:
    """
    Snap a NISAR granule's native extent to master-grid chunk boundaries.

    Reuses ``grid.snap_bbox(expand=True)`` + ``grid.compute_geogrid_for_bbox`` so NISAR
    and BIOMASS share the exact same snapping logic. The fill margin expands as needed
    to reach a whole number of 512×512 chunks.

    Args:
        transform: Native NISAR affine transform (pixel-corner origin)
        width, height: Native NISAR raster size in pixels
        grid: Target grid (spacing defines output posting; default 5×5)

    Returns:
        dict: Geogrid parameters (epsg, x_min/max, y_min/max, x_posting, y_posting,
              width, height) — same schema as the BIOMASS geogrid.
    """
    native_bounds = bounds_from_transform(transform, width, height)
    return grid.compute_geogrid_for_bbox(native_bounds, margin_m=0.0, snap_to_chunks=True)


def geogrid_transform(geogrid: Dict) -> Affine:
    """Build a north-up affine transform from a geogrid dict."""
    return Affine(
        geogrid["x_posting"], 0.0, geogrid["x_min"],
        0.0, -geogrid["y_posting"], geogrid["y_max"],
    )


def _is_integer(value: float, tol: float = 1e-6) -> bool:
    return abs(value - round(value)) < tol
