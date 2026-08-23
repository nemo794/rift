#!/usr/bin/env python3
"""
Regrid NISAR GSLC data onto the Antarctica master grid.

NISAR L2 GSLC products are already in EPSG:3031 at 5×5 m posting, so putting them on
the master grid is a **resample + chunk-boundary snap**, not a CRS reprojection.

Two signal-processing rules are enforced here (see docs/GRID_RESAMPLING_DECISION.md):

1. **Operate in the complex domain, detect last.** All resampling in this module takes
   and returns *complex* samples. The caller computes ``|·|`` afterwards. Detecting
   before resampling roughly doubles the signal bandwidth and would alias / corrupt
   speckle statistics.

2. **Anti-alias before decimating.** Any axis whose spacing increases (e.g. range
   5→40 m) is low-pass filtered (block-average boxcar for integer factors) *before*
   decimation. Nearest/bilinear alone would alias.

Lattice note: NISAR pixel edges already fall on integer multiples of 5 m from the
origin, which is the master-grid lattice. So the **default 5×5 target requires no
resampling** — it is a lossless windowed placement into a chunk-aligned canvas, which
also yields exact pixel co-registration with BIOMASS. Interpolation is only needed when
the target spacing differs or a granule's lattice is fractionally offset.
"""

from __future__ import annotations

from typing import Dict, Tuple

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


def decimation_factors(src_spacing: Tuple[float, float],
                       target_spacing: Tuple[float, float]) -> Tuple[float, float]:
    """
    Return (fy, fx) = target/src spacing ratios. >1 means downsampling (decimate) on
    that axis; <1 means upsampling (interpolate); ==1 means unchanged.
    """
    sx, sy = src_spacing
    tx, ty = target_spacing
    return (ty / sy, tx / sx)


def antialias_boxcar_complex(arr: np.ndarray, fy: int, fx: int) -> np.ndarray:
    """
    Anti-alias and decimate a complex array by integer factors via a boxcar average.

    A boxcar (block) average is the simplest separable anti-alias low-pass: averaging
    each fy×fx block suppresses energy above the new Nyquist before decimation. Real and
    imaginary parts are averaged independently (equivalent to averaging the complex
    samples), which is the correct multilook operation on complex SAR data.

    The array is trimmed to whole blocks (any partial trailing block is dropped).

    Args:
        arr: Complex 2-D array (rows=y, cols=x)
        fy, fx: Integer decimation factors (>=1)

    Returns:
        Complex 2-D array of shape (rows//fy, cols//fx)
    """
    if fy < 1 or fx < 1:
        raise ValueError(f"Decimation factors must be >= 1, got fy={fy}, fx={fx}")
    if fy == 1 and fx == 1:
        return arr

    rows, cols = arr.shape
    out_rows = rows // fy
    out_cols = cols // fx
    trimmed = arr[: out_rows * fy, : out_cols * fx]
    # Reshape into blocks and average over the block axes (complex mean = multilook).
    blocks = trimmed.reshape(out_rows, fy, out_cols, fx)
    return blocks.mean(axis=(1, 3))


def _is_integer(value: float, tol: float = 1e-6) -> bool:
    return abs(value - round(value)) < tol


def regrid_complex(
    complex_array: np.ndarray,
    src_transform: Affine,
    target_geogrid: Dict,
    src_spacing: Tuple[float, float],
    method: str = "nearest",
    antialias: bool = True,
) -> np.ndarray:
    """
    Resample a complex NISAR array from its native grid onto ``target_geogrid``.

    Operates entirely in the complex domain (detect last). Chooses a path automatically:

    * **Same spacing, integer pixel offset** (the default 5×5 case): lossless windowed
      placement — native samples are copied into a chunk-aligned canvas at the correct
      integer offset; the rest is NaN. No interpolation.
    * **Downsampling** (target spacing > src, integer factor): boxcar anti-alias +
      decimate (see :func:`antialias_boxcar_complex`), then windowed placement.
    * **Otherwise** (upsampling / fractional factor / fractional offset): complex
      interpolation with ``scipy.ndimage.map_coordinates`` (``method`` selects order:
      nearest=0, bilinear=1, else cubic=3) applied to real and imaginary parts.

    Args:
        complex_array: Native complex64 array (rows=y, cols=x)
        src_transform: Native north-up affine transform (pixel-corner origin)
        target_geogrid: Target geogrid dict from :func:`compute_nisar_target_geogrid`
        src_spacing: (x_spacing, y_spacing) of the native grid, meters
        method: Interpolation kernel for the resample path
            (nearest | bilinear | lanczos/cubic)
        antialias: Apply anti-alias low-pass before any downsampling (strongly
            recommended; disabling risks aliasing)

    Returns:
        Complex64 array of shape (target_geogrid['height'], target_geogrid['width']),
        NaN+NaNj where no native data maps.
    """
    out_h = target_geogrid["height"]
    out_w = target_geogrid["width"]
    tx = target_geogrid["x_posting"]
    ty = target_geogrid["y_posting"]
    invalid = np.complex64(np.nan + 1j * np.nan)

    fy, fx = decimation_factors(src_spacing, (tx, ty))

    same_spacing = _is_integer(fy) and _is_integer(fx) and round(fy) == 1 and round(fx) == 1
    integer_downsample = (
        fy >= 1 and fx >= 1 and _is_integer(fy) and _is_integer(fx)
        and (round(fy) > 1 or round(fx) > 1)
    )

    if same_spacing or integer_downsample:
        # --- Anti-alias + decimate (no-op when factors are 1) -------------------------
        src = complex_array
        src_x0 = src_transform.c
        src_y0 = src_transform.f
        if integer_downsample:
            ify, ifx = round(fy), round(fx)
            if antialias:
                src = antialias_boxcar_complex(src, ify, ifx)
            else:
                src = src[::ify, ::ifx]
            # Decimated pixel-corner origin is unchanged (top-left corner preserved).

        # --- Windowed placement into the chunk-aligned canvas -------------------------
        # Integer pixel offset of the (possibly decimated) source within the target grid.
        col_off = (src_x0 - target_geogrid["x_min"]) / tx
        row_off = (target_geogrid["y_max"] - src_y0) / ty

        if _is_integer(col_off) and _is_integer(row_off):
            out = np.full((out_h, out_w), invalid, dtype=np.complex64)
            c0, r0 = int(round(col_off)), int(round(row_off))
            sh, sw = src.shape
            # Clip source to the target canvas.
            tr0, tc0 = max(r0, 0), max(c0, 0)
            sr0, sc0 = max(-r0, 0), max(-c0, 0)
            h = min(sh - sr0, out_h - tr0)
            w = min(sw - sc0, out_w - tc0)
            if h > 0 and w > 0:
                out[tr0:tr0 + h, tc0:tc0 + w] = src[sr0:sr0 + h, sc0:sc0 + w]
            return out
        # Fractional offset → fall through to interpolation on the (decimated) source.
        complex_array = src
        src_transform = Affine(tx, 0.0, src_x0, 0.0, -ty, src_y0)

    # --- General interpolation path (upsample / fractional) ---------------------------
    from scipy.ndimage import map_coordinates

    order = {"nearest": 0, "bilinear": 1}.get(method, 3)
    target_tf = geogrid_transform(target_geogrid)

    # Target pixel-center coordinates (EPSG:3031).
    cols = np.arange(out_w)
    rows = np.arange(out_h)
    x_centers = target_tf.c + (cols + 0.5) * target_tf.a
    y_centers = target_tf.f + (rows + 0.5) * target_tf.e
    xx, yy = np.meshgrid(x_centers, y_centers)

    # Map to source fractional pixel indices.
    src_col = (xx - src_transform.c) / src_transform.a - 0.5
    src_row = (yy - src_transform.f) / src_transform.e - 0.5

    coords = np.vstack([src_row.ravel(), src_col.ravel()])
    real = map_coordinates(complex_array.real, coords, order=order,
                           mode="constant", cval=np.nan).reshape(out_h, out_w)
    imag = map_coordinates(complex_array.imag, coords, order=order,
                           mode="constant", cval=np.nan).reshape(out_h, out_w)
    return (real + 1j * imag).astype(np.complex64)
