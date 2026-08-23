#!/usr/bin/env python3
"""
Extract amplitude from a NISAR GSLC HDF5 file and regrid onto the master grid.

Extracts all **frequency A** polarization layers (HH, HV, VV, VH) — frequency B is
ignored — computes amplitude (phase discarded), applies masks, snaps/resamples onto the
Antarctica master grid, and writes one Cloud-Optimized GeoTIFF per polarization.

Signal-processing rules (see docs/GRID_RESAMPLING_DECISION.md, docs/NISAR_WORKFLOW.md):
    * Masks are applied to the **complex** samples (set to NaN) *before* detection, and
      resampling happens in the complex domain — amplitude ``|·|`` is taken last.
    * Any downsampled axis is anti-alias filtered (boxcar multilook) before decimation.

Masking logic:
    1. Main mask (frequencyA/mask): 0 = invalid → NaN (all polarizations).
    2. Anomaly mask (frequencyA/inputDataExceptionMask): applied ONLY to HV,
       >= 1 = invalid → NaN.

Grid modes:
    * Default: target = master grid at 5×5 m. NISAR pixel edges already lie on the 5 m
      lattice, so this is a lossless windowed placement into a chunk-aligned canvas
      (exact co-registration with BIOMASS), no interpolation.
    * ``native=True``: keep 5×5 native posting, snap the extent to chunk boundaries only.
    * Coarser target spacing (e.g. 5×40): integer boxcar multilook + windowed placement.

Memory:
    * Native / same-spacing / integer-downsample paths stream in 512-pixel source tiles.
    * The general fractional/upsample path loads the full complex array (warns first).

Usage:
    python -m rift.nisar.extract NISAR_L2_PR_GSLC_*.h5
    python -m rift.nisar.extract NISAR_*.h5 --polarizations HH HV --native
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import h5py
import numpy as np
from rasterio.transform import Affine

from rift.cogutil import base_profile, finalize_cog
from rift.grid import ANTARCTICA_GRID, AntarcticaGrid
from rift.nisar.regrid import (
    antialias_boxcar_complex,
    compute_nisar_target_geogrid,
    decimation_factors,
    geogrid_transform,
    regrid_complex,
    _is_integer,
)

import rasterio

FREQ_A = "/science/LSAR/GSLC/grids/frequencyA"

# Optional progress bar
try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable=None, total=None, desc=None, unit=None):
        if iterable is not None:
            return iterable

        class FakeTqdm:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def update(self, n):
                pass

        return FakeTqdm()


def read_polarizations_list(h5_file):
    """Read the list of available frequency-A polarizations from the HDF5 file."""
    pol_path = f"{FREQ_A}/listOfPolarizations"
    with h5py.File(h5_file, "r") as f:
        if pol_path not in f:
            raise ValueError(f"Could not find {pol_path} in HDF5 file")
        pols_raw = f[pol_path][()]
        pols = [p.decode("utf-8") if isinstance(p, bytes) else p for p in pols_raw]
    return pols


def extract_geotransform(h5_file):
    """
    Extract native georeferencing parameters from a NISAR GSLC HDF5 file.

    Returns:
        dict: epsg, transform (pixel-corner, north-up), width, height, x_spacing, y_spacing
    """
    with h5py.File(h5_file, "r") as f:
        epsg = int(f[f"{FREQ_A}/projection"][()])
        x_coords = f[f"{FREQ_A}/xCoordinates"][:]
        y_coords = f[f"{FREQ_A}/yCoordinates"][:]
        x_spacing = float(f[f"{FREQ_A}/xCoordinateSpacing"][()])
        y_spacing = float(f[f"{FREQ_A}/yCoordinateSpacing"][()])

        height = len(y_coords)
        width = len(x_coords)

        # HDF5 stores pixel centers; GDAL expects the pixel corner (shift by half pixel).
        x_min = x_coords[0] - x_spacing / 2.0
        y_max = y_coords[0] - y_spacing / 2.0  # y_spacing is negative

        transform = Affine(x_spacing, 0.0, x_min, 0.0, y_spacing, y_max)

    return {
        "epsg": epsg,
        "transform": transform,
        "width": width,
        "height": height,
        "x_spacing": x_spacing,
        "y_spacing": y_spacing,
    }


def read_masked_complex(pol_data, mask_data, anomaly_data, pol_name, row_slice, col_slice):
    """
    Read a complex tile and apply masks in the complex domain (invalid → NaN+NaNj).

    Masking before detection/resampling keeps the amplitude statistics consistent: NaN
    propagates through detection and (via nan-aware multilook) through downsampling.
    """
    tile = pol_data[row_slice, col_slice].astype(np.complex64)

    mask_tile = mask_data[row_slice, col_slice]
    invalid = np.complex64(np.nan + 1j * np.nan)
    tile[mask_tile == 0] = invalid

    if pol_name == "HV" and anomaly_data is not None:
        anomaly_tile = anomaly_data[row_slice, col_slice]
        tile[anomaly_tile >= 1] = invalid

    return tile


# --------------------------------------------------------------------------------------
# Streaming placement (native / same-spacing / integer downsample)
# --------------------------------------------------------------------------------------

def _stream_placement(dst, pol_data, mask_data, anomaly_data, pol, geo_info,
                      target_geogrid, ify, ifx, antialias, tile_size):
    """
    Stream source tiles → detect → place into the chunk-aligned output canvas.

    Handles native (ify=ifx=1, target==native extent), same-spacing windowed placement,
    and integer downsampling (ify/ifx > 1). Source tiles are read as whole multiples of
    the decimation factor so boxcar multilook blocks are complete.
    """
    src_tf = geo_info["transform"]
    tx = target_geogrid["x_posting"]
    ty = target_geogrid["y_posting"]
    height, width = pol_data.shape

    # Integer pixel offset of the decimated source origin within the target canvas.
    col_off = int(round((src_tf.c - target_geogrid["x_min"]) / tx))
    row_off = int(round((target_geogrid["y_max"] - src_tf.f) / ty))

    out_h = target_geogrid["height"]
    out_w = target_geogrid["width"]

    # Source tile step is a whole number of output pixels (multiple of the factor).
    step_r = tile_size * ify
    step_c = tile_size * ifx
    n_tiles_y = (height + step_r - 1) // step_r
    n_tiles_x = (width + step_c - 1) // step_c

    with tqdm(total=n_tiles_y * n_tiles_x, desc=f"  {pol}", unit="tile") as pbar:
        for i in range(n_tiles_y):
            for j in range(n_tiles_x):
                r0 = i * step_r
                c0 = j * step_c
                r1 = min(r0 + step_r, height)
                c1 = min(c0 + step_c, width)

                tile = read_masked_complex(pol_data, mask_data, anomaly_data, pol,
                                           slice(r0, r1), slice(c0, c1))

                if ify > 1 or ifx > 1:
                    if antialias:
                        tile = antialias_boxcar_complex(tile, ify, ifx)
                    else:
                        tile = tile[::ify, ::ifx]
                    out_r = r0 // ify + row_off
                    out_c = c0 // ifx + col_off
                else:
                    out_r = r0 + row_off
                    out_c = c0 + col_off

                amp = np.abs(tile).astype(np.float32)

                # Clip to the output canvas.
                th, tw = amp.shape
                tr0 = max(out_r, 0)
                tc0 = max(out_c, 0)
                sr0 = max(-out_r, 0)
                sc0 = max(-out_c, 0)
                h = min(th - sr0, out_h - tr0)
                w = min(tw - sc0, out_w - tc0)
                if h > 0 and w > 0:
                    dst.write(
                        amp[sr0:sr0 + h, sc0:sc0 + w], 1,
                        window=rasterio.windows.Window(tc0, tr0, w, h),
                    )
                pbar.update(1)


def process_single_polarization(h5_file, pol, geo_info, output_file, tile_size=512,
                                 grid: AntarcticaGrid = ANTARCTICA_GRID, native=False,
                                 method="nearest", antialias=True):
    """
    Extract amplitude for one polarization, regrid onto the master grid, write a COG.

    Args:
        h5_file: Path to NISAR GSLC HDF5 file
        pol: Polarization name (e.g. 'HH')
        geo_info: Native georeferencing dict from extract_geotransform()
        output_file: Output COG path
        tile_size: Streaming tile size (default 512, matches HDF5 chunks)
        grid: Target master grid (spacing defines output posting)
        native: If True, keep native 5×5 posting (snap extent only, no resample)
        method: Interpolation kernel for the general resample path
        antialias: Anti-alias before downsampling (recommended)
    """
    print(f"\nProcessing polarization: {pol}")
    print(f"  Output: {output_file.name}")

    if native:
        grid = grid.with_spacing(geo_info["x_spacing"], abs(geo_info["y_spacing"]))

    target_geogrid = compute_nisar_target_geogrid(
        geo_info["transform"], geo_info["width"], geo_info["height"], grid=grid
    )
    target_tf = geogrid_transform(target_geogrid)

    src_spacing = (geo_info["x_spacing"], abs(geo_info["y_spacing"]))
    fy, fx = decimation_factors(src_spacing, (target_geogrid["x_posting"],
                                              target_geogrid["y_posting"]))
    integer_factors = _is_integer(fy) and _is_integer(fx) and fy >= 1 and fx >= 1

    print(f"  Target grid: {target_geogrid['width']} x {target_geogrid['height']} px "
          f"@ {target_geogrid['x_posting']}×{target_geogrid['y_posting']} m")

    profile = base_profile(
        width=target_geogrid["width"], height=target_geogrid["height"],
        epsg=target_geogrid["epsg"], transform=target_tf,
        dtype="float32", count=1, nodata=np.nan, blocksize=512,
    )
    temp_file = output_file.with_suffix(".temp.tif")

    with h5py.File(h5_file, "r") as h5f:
        pol_path = f"{FREQ_A}/{pol}"
        if pol_path not in h5f:
            raise ValueError(f"Polarization {pol} not found in HDF5 file")
        pol_data = h5f[pol_path]
        mask_data = h5f[f"{FREQ_A}/mask"]
        anomaly_path = f"{FREQ_A}/inputDataExceptionMask"
        anomaly_data = h5f[anomaly_path] if anomaly_path in h5f else None
        if anomaly_data is None and pol == "HV":
            print("  Warning: inputDataExceptionMask not found, skipping anomaly mask")

        # Check the source origin lands on integer output pixels (windowed placement OK).
        col_off = (geo_info["transform"].c - target_geogrid["x_min"]) / target_geogrid["x_posting"]
        row_off = (target_geogrid["y_max"] - geo_info["transform"].f) / target_geogrid["y_posting"]
        can_stream = integer_factors and _is_integer(col_off / max(round(fx), 1)) \
            and _is_integer(row_off / max(round(fy), 1))

        with rasterio.open(temp_file, "w", **profile) as dst:
            if can_stream:
                _stream_placement(dst, pol_data, mask_data, anomaly_data, pol, geo_info,
                                  target_geogrid, round(fy), round(fx), antialias, tile_size)
            else:
                print("  ⚠ Fractional/upsample regrid — loading full complex array "
                      "(high memory).")
                full = read_masked_complex(pol_data, mask_data, anomaly_data, pol,
                                           slice(0, geo_info["height"]),
                                           slice(0, geo_info["width"]))
                regridded = regrid_complex(full, geo_info["transform"], target_geogrid,
                                           src_spacing, method=method, antialias=antialias)
                dst.write(np.abs(regridded).astype(np.float32), 1)

            dst.set_band_description(1, f"{pol} Amplitude")
            dst.update_tags(1, POLARIZATION=pol, BAND_TYPE="amplitude")
            dst.update_tags(
                SOURCE_FILE=Path(h5_file).name,
                FREQUENCY="A",
                POSTING=f"{target_geogrid['x_posting']}m × {target_geogrid['y_posting']}m",
                GRID_EPSG=str(target_geogrid["epsg"]),
                PROCESSING="NISAR GSLC freqA amplitude, masked (complex domain), regridded to master grid",
                MASK_LOGIC="Main mask: 0=invalid; Anomaly mask (HV only): >=1=invalid",
            )

    print("  Converting to Cloud-Optimized GeoTIFF...")
    finalize_cog(temp_file, output_file)
    print(f"  ✓ Complete: {output_file.stat().st_size / 1e6:.1f} MB")


def extract_amplitude_to_cogs(h5_file, output_dir=None, polarizations=None, tile_size=512,
                              grid: AntarcticaGrid = ANTARCTICA_GRID, native=False,
                              method="nearest", antialias=True):
    """
    Extract amplitude from frequency-A polarizations → one regridded COG per polarization.

    Args:
        h5_file: Path to NISAR GSLC HDF5 file
        output_dir: Output directory (default: same as input file)
        polarizations: Polarizations to process (default: all available in freq A)
        tile_size: Streaming tile size (default 512)
        grid: Target master grid (spacing defines output posting; default 5×5)
        native: Keep native 5×5 posting (snap extent only)
        method: Interpolation kernel for the general resample path
        antialias: Anti-alias before downsampling

    Returns:
        list[Path]: Created output files
    """
    print(f"Processing: {h5_file}")

    available_pols = read_polarizations_list(h5_file)
    print(f"Available frequency-A polarizations: {available_pols}")

    if polarizations is not None:
        pols_to_process = [p for p in polarizations if p in available_pols]
        if not pols_to_process:
            raise ValueError(
                f"None of the requested polarizations {polarizations} found in file"
            )
        missing = set(polarizations) - set(pols_to_process)
        if missing:
            print(f"Warning: Polarizations {missing} not found, skipping")
    else:
        pols_to_process = available_pols

    print(f"Processing polarizations: {pols_to_process}")

    geo_info = extract_geotransform(h5_file)
    print(f"Native size: {geo_info['width']} x {geo_info['height']} px")
    print(f"Native EPSG: {geo_info['epsg']}, spacing "
          f"{geo_info['x_spacing']}m x {geo_info['y_spacing']}m")

    if output_dir is None:
        output_dir = Path(h5_file).parent
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

    output_files = []
    base_name = Path(h5_file).stem

    for pol in pols_to_process:
        output_file = output_dir / f"{base_name}_{pol}_amp.tif"
        try:
            process_single_polarization(
                h5_file, pol, geo_info, output_file, tile_size,
                grid=grid, native=native, method=method, antialias=antialias,
            )
            output_files.append(output_file)
        except Exception as e:
            print(f"  ✗ Failed to process {pol}: {e}")
            continue

    return output_files


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("input", type=Path, help="NISAR GSLC HDF5 file")
    parser.add_argument("--output-dir", type=Path,
                        help="Output directory (default: same as input file)")
    parser.add_argument("--polarizations", nargs="+", choices=["HH", "HV", "VV", "VH"],
                        help="Specific polarizations to process (default: all in freq A)")
    parser.add_argument("--tile-size", type=int, default=512,
                        help="Streaming tile size (default: 512)")
    parser.add_argument("--x-spacing", type=float, default=5.0,
                        help="Target grid X spacing in meters (default: 5)")
    parser.add_argument("--y-spacing", type=float, default=5.0,
                        help="Target grid Y spacing in meters (default: 5)")
    parser.add_argument("--native", action="store_true",
                        help="Keep native 5×5 posting (snap extent only)")
    parser.add_argument("--resampling", default="nearest",
                        choices=["nearest", "bilinear", "lanczos", "average"],
                        help="Interpolation kernel for the general resample path")
    parser.add_argument("--no-antialias", action="store_true",
                        help="Disable anti-alias low-pass before downsampling (risky)")

    args = parser.parse_args()

    if not args.input.exists():
        print(f"ERROR: Input file not found: {args.input}")
        return 1

    grid = ANTARCTICA_GRID.with_spacing(args.x_spacing, args.y_spacing)

    try:
        output_files = extract_amplitude_to_cogs(
            args.input, args.output_dir, args.polarizations, args.tile_size,
            grid=grid, native=args.native, method=args.resampling,
            antialias=not args.no_antialias,
        )
        print(f"\n{'='*70}\nSUCCESS!\n{'='*70}")
        print(f"Created {len(output_files)} file(s):")
        for f in output_files:
            print(f"  {f}")
        return 0
    except Exception as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
