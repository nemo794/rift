#!/usr/bin/env python3
"""
Geocode a BIOMASS granule to a custom geogrid.

This script geocodes a BIOMASS L1A SCS granule to a user-specified geogrid,
creating a Cloud-Optimized GeoTIFF with amplitude (and optionally phase).

Usage:
    python rift.biomass.geocode \
        --biomass-granule /path/to/BIOMASS/scene \
        --geogrid biomass_geogrid.json \
        --dem dem_epsg3031.tif \
        --output biomass_gslc.tif \
        --polarization HH

Arguments:
    --biomass-granule:  BIOMASS L1A SCS granule directory or .zip file
    --geogrid:          JSON file with geogrid parameters (from rift.biomass.geogrid)
    --dem:              DEM file in EPSG:3031
    --output:           Output COG file
    --polarization:     Polarization to process (HH, HV, VH, VV)
    --amp-only:         Write amplitude only (default: also write a separate phase COG)

Outputs (one single-band COG each, mirroring the source L1A abs/phase layout):
    <output>:      Amplitude (linear amplitude of complex SAR signal)
    <output>_phs:  Phase (in radians, range: -π to +π) [unless --amp-only]
"""

import argparse
import sys
import json
from pathlib import Path
from datetime import datetime
import re
import zipfile

import numpy as np
import rasterio
from rasterio.transform import Affine
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds

from biomass_reader import BiomassSlc
from biomass_reader._constants import POLARIZATION_ORDER
import isce3

from rift.cogutil import base_profile, write_cog, finalize_cog
from rift.biomass.geogrid import ensure_granule_dir


class DemCoverageError(Exception):
    """Raised when a provided DEM does not cover the output geocoded radar swath."""


def read_available_polarizations(granule_path):
    """
    Detect which polarizations have valid data in a BIOMASS granule.

    BIOMASS L1A SCS products store amplitude and phase as 4-band GeoTIFFs in the order
    HH, HV, VH, VV. This function checks which bands contain non-zero data to determine
    which polarizations are actually available in the product.

    Args:
        granule_path: Path to BIOMASS L1A SCS granule directory or .zip file

    Returns:
        list: Available polarizations (e.g., ['HH', 'HV', 'VH', 'VV'])
    """
    granule_path = Path(granule_path)
    granule_path = ensure_granule_dir(granule_path)

    measurement_dir = granule_path / "measurement"
    if not measurement_dir.exists():
        raise ValueError(f"Measurement directory not found: {measurement_dir}")

    abs_file = list(measurement_dir.glob("*abs*.tiff"))
    if not abs_file:
        raise ValueError(f"No amplitude file found in {measurement_dir}")
    abs_file = abs_file[0]

    available_pols = []
    with rasterio.open(abs_file) as src:
        for idx, pol in enumerate(POLARIZATION_ORDER, start=1):
            band = src.read(idx, window=rasterio.windows.Window(0, 0, 100, 100))
            if np.any(band != 0):
                available_pols.append(pol)

    return available_pols


def check_dem_covers_grid(dem_file, grid_params, min_valid_fraction=0.0):
    """
    Fail early if a provided DEM does not cover the output geocoding grid.

    Checks two things against the chunk-aligned output grid (which already includes the
    swath margin): (1) the DEM's extent must fully contain the grid, and (2) the DEM must
    actually hold valid elevation data over the grid — an extent that merely *overlaps* is
    not enough, since a DEM cropped to a different swath can be all-nodata here.

    The grid bbox (EPSG from ``grid_params``) is reprojected into the DEM's CRS, so a DEM
    in EPSG:4326 (as returned by the sardem auto-download) is handled correctly.

    Args:
        dem_file: Path to the DEM raster
        grid_params: Geogrid dict (x_min/x_max/y_min/y_max, epsg, width, height)
        min_valid_fraction: Minimum fraction of sampled grid pixels that must be valid
            (default 0.0 → require at least one valid pixel). Raise the threshold to also
            reject DEMs that are mostly nodata over the swath.

    Raises:
        DemCoverageError: If the DEM does not spatially contain the grid or has no valid
            data over it.
    """
    guidance = (
        "Provided DEM does not cover the output geocoded radar swath. Either provide a "
        "DEM that corresponds to the input granule, or omit the --dem option to let the "
        "algorithm auto-fetch the correct DEM."
    )

    with rasterio.open(dem_file) as dem:
        # Grid bbox in the grid's CRS, reprojected into the DEM's CRS for comparison.
        grid_epsg = grid_params['epsg']
        gx_min, gx_max = grid_params['x_min'], grid_params['x_max']
        gy_min, gy_max = grid_params['y_min'], grid_params['y_max']

        if dem.crs is None:
            raise DemCoverageError(f"{guidance} (DEM has no CRS defined: {dem_file})")

        dem_epsg = dem.crs.to_epsg()
        if dem_epsg is not None and dem_epsg != grid_epsg:
            left, bottom, right, top = transform_bounds(
                f"EPSG:{grid_epsg}", dem.crs, gx_min, gy_min, gx_max, gy_max
            )
        else:
            left, bottom, right, top = gx_min, gy_min, gx_max, gy_max

        # (1) Extent containment (allow one pixel of tolerance on each edge).
        db = dem.bounds
        tol_x = abs(dem.transform.a)
        tol_y = abs(dem.transform.e)
        if (left < db.left - tol_x or right > db.right + tol_x or
                bottom < db.bottom - tol_y or top > db.top + tol_y):
            raise DemCoverageError(
                f"{guidance}\n"
                f"    Grid bbox (DEM CRS): [{left:.1f}, {bottom:.1f}, {right:.1f}, {top:.1f}]\n"
                f"    DEM bounds:          [{db.left:.1f}, {db.bottom:.1f}, {db.right:.1f}, {db.top:.1f}]"
            )

        # (2) Valid-data check: read the grid region (decimated) and require valid pixels.
        try:
            window = from_bounds(left, bottom, right, top, dem.transform)
            # Decimate to a bounded sample (~512 px per side) to keep this cheap.
            out_h = min(512, max(1, int(round(window.height))))
            out_w = min(512, max(1, int(round(window.width))))
            sample = dem.read(1, window=window, out_shape=(out_h, out_w),
                              boundless=True, fill_value=dem.nodata if dem.nodata is not None else np.nan)
        except Exception as e:
            raise DemCoverageError(f"{guidance} (failed to read DEM over grid: {e})")

        finite = np.isfinite(sample)
        if dem.nodata is not None:
            finite &= (sample != dem.nodata)
        valid_fraction = float(np.count_nonzero(finite)) / finite.size

        if valid_fraction <= min_valid_fraction:
            raise DemCoverageError(
                f"{guidance}\n"
                f"    DEM extent contains the grid, but only {valid_fraction:.1%} of the "
                f"swath region has valid elevation data (nodata elsewhere)."
            )

    return True


def load_geogrid_params(geogrid_file):
    """
    Load geogrid parameters from JSON file.

    Returns:
        dict: Grid parameters
    """
    print(f"Reading geogrid parameters from: {geogrid_file}")

    with open(geogrid_file, 'r') as f:
        grid_params = json.load(f)

    print("\nGeogrid Parameters:")
    print(f"  EPSG: {grid_params['epsg']}")
    print(f"  Posting: {grid_params['x_posting']}m × {grid_params['y_posting']}m")
    print(f"  Dimensions: {grid_params['width']} × {grid_params['height']} pixels")
    print(f"  Extent: ({grid_params['x_min']:.0f}, {grid_params['y_min']:.0f}) to ({grid_params['x_max']:.0f}, {grid_params['y_max']:.0f})")

    return grid_params


def extract_acquisition_time(granule_path):
    """
    Extract acquisition time from BIOMASS granule filename.

    Pattern: BIO_S*_SCS__1S_YYYYMMDDTHHMMSS_...

    Returns:
        datetime: Acquisition time
    """
    pattern = re.compile(r'BIO_S\d+_SCS__1S_(\d{8}T\d{6})_')
    match = pattern.search(granule_path.name)

    if not match:
        raise ValueError(f"Could not parse acquisition time from: {granule_path.name}")

    time_str = match.group(1)
    return datetime.strptime(time_str, '%Y%m%dT%H%M%S')


def geocode_biomass_granule(granule_path, dem_file, grid_params, polarization):
    """
    Geocode one BIOMASS granule to the specified grid.

    Returns:
        tuple: (complex_array, acquisition_time)
    """
    granule_path = Path(granule_path)

    # Get acquisition time
    acq_time = extract_acquisition_time(granule_path)

    print(f"\nProcessing: {granule_path.name}")
    print(f"Acquisition: {acq_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")

    # Fail early: verify the provided DEM covers the (margined, chunk-aligned) output grid
    # before doing any expensive SLC loading or geocoding.
    print(f"  Checking DEM coverage of output grid...")
    check_dem_covers_grid(dem_file, grid_params)

    # Unzip if needed (shared with footprint computation)
    granule_path = ensure_granule_dir(granule_path)

    print(f"  Loading BIOMASS SLC...")
    slc = BiomassSlc.from_dir(granule_path, polarization=polarization)

    print(f"  Setting up geocoding grid...")
    # Create isce3 GeoGridParameters
    geogrid = isce3.product.GeoGridParameters(
        start_x=grid_params['x_min'],
        start_y=grid_params['y_max'],
        spacing_x=grid_params['x_posting'],
        spacing_y=-grid_params['y_posting'],  # Negative for north-up
        width=grid_params['width'],
        length=grid_params['height'],
        epsg=grid_params['epsg']
    )

    print(f"  Geocoding to {geogrid.width} × {geogrid.length} grid...")

    # Prepare DEM
    dem = isce3.io.Raster(str(dem_file))
    dem_epsg = dem.get_epsg()

    # Validate DEM projection
    if dem_epsg != geogrid.epsg:
        print(f"\n  ⚠️  WARNING: DEM projection mismatch!")
        print(f"    DEM EPSG: {dem_epsg}")
        print(f"    Geogrid EPSG: {geogrid.epsg}")
        print(f"    This may cause issues. Consider reprojecting DEM to EPSG:{geogrid.epsg}")

    ellipsoid = isce3.core.make_projection(geogrid.epsg).ellipsoid
    invalid = np.complex64(np.nan + 1j * np.nan)
    output = np.full((geogrid.length, geogrid.width), invalid, dtype=np.complex64)

    # Geocode
    isce3.geocode.geocode_slc(
        geo_data_blocks=[output],
        rdr_data_blocks=[slc.read_complex()],
        dem_raster=dem,
        radargrid=slc.radar_grid,
        geogrid=geogrid,
        orbit=slc.orbit,
        native_doppler=slc.doppler,
        image_grid_doppler=isce3.core.LUT2d(),
        ellipsoid=ellipsoid,
        threshold_geo2rdr=1.0e-8,
        num_iter_geo2rdr=25,
        flatten=True,
        invalid_value=invalid,
    )

    # Count valid pixels
    valid_count = np.sum(~np.isnan(np.abs(output)))
    valid_percent = 100 * valid_count / output.size
    print(f"  Valid pixels: {valid_count:,} ({valid_percent:.1f}%)")

    if valid_count == 0:
        print("\n  ⚠ WARNING: 0 valid pixels!")
        print("  This usually means:")
        print("    - DEM doesn't cover the geocoding grid")
        print("    - Or radar data doesn't overlap with the grid")
    elif valid_percent < 10:
        print(f"\n  ⚠ WARNING: Low coverage ({valid_percent:.1f}%)")
        print("  Check that DEM fully covers the geocoding grid")

    return output, acq_time


def geocode_biomass_to_cogs(granule_path, dem_file, grid_params, polarization,
                            output_file, metadata, *, phase_file=None, block_rows=512):
    """
    Geocode one BIOMASS polarization to amplitude (and phase) COGs, block by block.

    Memory-bounded alternative to ``geocode_biomass_granule`` + ``write_biomass_cog``:
    instead of allocating the full geocoded grid in RAM (complex64, ~11 GB at a 3 m posting
    over a typical swath), this geocodes the output ``block_rows`` at a time and streams
    each block's amplitude/phase straight to disk. Peak memory is the (fixed-size) radar
    SLC plus one output block, independent of the output resolution.

    Blocks are geocoded independently: ``isce3.geocode.geocode_slc`` resolves every output
    pixel via its own geo2rdr solve, so a full-width row-block sub-geogrid produces exactly
    the same pixels as the whole-grid call — no seams, no halo/overlap needed.

    Args:
        granule_path: BIOMASS L1A SCS granule directory or .zip file
        dem_file: DEM raster path
        grid_params: Geogrid dict (x_min/x_max/y_min/y_max, x_posting/y_posting,
            width/height, epsg) — the full output grid
        polarization: Polarization to geocode (HH/HV/VH/VV)
        output_file: Destination amplitude COG path
        metadata: Dataset-level tag dict (as built by the pipeline / CLI)
        phase_file: Destination phase COG path, or None to skip phase output
        block_rows: Output rows geocoded per block (default 512, matches the 512-px COG
            chunk height so window writes land on chunk boundaries)

    Returns:
        list[Path]: COG(s) written (amplitude first, then phase if any)
    """
    import contextlib

    granule_path = Path(granule_path)
    output_file = Path(output_file)
    include_phase = phase_file is not None
    if include_phase:
        phase_file = Path(phase_file)

    acq_time = extract_acquisition_time(granule_path)

    print(f"\nProcessing: {granule_path.name}")
    print(f"Acquisition: {acq_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")

    # Fail early: verify the provided DEM covers the (margined, chunk-aligned) output grid
    # before doing any expensive SLC loading or geocoding.
    print(f"  Checking DEM coverage of output grid...")
    check_dem_covers_grid(dem_file, grid_params)

    # Unzip if needed (shared with footprint computation)
    granule_path = ensure_granule_dir(granule_path)

    print(f"  Loading BIOMASS SLC...")
    slc = BiomassSlc.from_dir(granule_path, polarization=polarization)
    # Read the radar-coordinate SLC once and keep it resident: it is the fixed-size input
    # (native scene dimensions), small relative to a fine-posting output grid.
    radar_slc = slc.read_complex()

    width = grid_params['width']
    height = grid_params['height']

    # Shared geocoding inputs (built once, reused for every block).
    dem = isce3.io.Raster(str(dem_file))
    dem_epsg = dem.get_epsg()
    if dem_epsg != grid_params['epsg']:
        print(f"\n  ⚠️  WARNING: DEM projection mismatch!")
        print(f"    DEM EPSG: {dem_epsg}")
        print(f"    Geogrid EPSG: {grid_params['epsg']}")
        print(f"    This may cause issues. Consider reprojecting DEM to EPSG:{grid_params['epsg']}")

    ellipsoid = isce3.core.make_projection(grid_params['epsg']).ellipsoid
    image_grid_doppler = isce3.core.LUT2d()
    invalid = np.complex64(np.nan + 1j * np.nan)

    band_desc = "amplitude + phase (separate files)" if include_phase else "amplitude only"
    n_blocks = (height + block_rows - 1) // block_rows
    print(f"  Geocoding {width} × {height} grid in {n_blocks} block(s) of "
          f"≤{block_rows} rows ({band_desc})...")

    transform = Affine(
        grid_params['x_posting'], 0.0, grid_params['x_min'],
        0.0, -grid_params['y_posting'], grid_params['y_max']
    )
    profile = base_profile(
        width=width, height=height, epsg=grid_params['epsg'], transform=transform,
        dtype='float32', count=1, nodata=np.nan,
    )

    temp_amp = output_file.with_suffix('.temp.tif')
    temp_phase = phase_file.with_suffix('.temp.tif') if include_phase else None

    valid_count = 0
    with contextlib.ExitStack() as stack:
        dst_amp = stack.enter_context(rasterio.open(temp_amp, 'w', **profile))
        dst_phase = (stack.enter_context(rasterio.open(temp_phase, 'w', **profile))
                     if include_phase else None)

        for r0 in range(0, height, block_rows):
            n = min(block_rows, height - r0)

            # Full-width sub-geogrid for this block: same lattice, shifted origin, n rows.
            block_geogrid = isce3.product.GeoGridParameters(
                start_x=grid_params['x_min'],
                start_y=grid_params['y_max'] - r0 * grid_params['y_posting'],
                spacing_x=grid_params['x_posting'],
                spacing_y=-grid_params['y_posting'],
                width=width,
                length=n,
                epsg=grid_params['epsg'],
            )

            output = np.full((n, width), invalid, dtype=np.complex64)
            isce3.geocode.geocode_slc(
                geo_data_blocks=[output],
                rdr_data_blocks=[radar_slc],
                dem_raster=dem,
                radargrid=slc.radar_grid,
                geogrid=block_geogrid,
                orbit=slc.orbit,
                native_doppler=slc.doppler,
                image_grid_doppler=image_grid_doppler,
                ellipsoid=ellipsoid,
                threshold_geo2rdr=1.0e-8,
                num_iter_geo2rdr=25,
                flatten=True,
                invalid_value=invalid,
            )

            window = rasterio.windows.Window(0, r0, width, n)
            amp = np.abs(output).astype(np.float32)
            valid_count += int(np.sum(~np.isnan(amp)))
            dst_amp.write(amp, 1, window=window)
            del amp

            if include_phase:
                phase = np.angle(output).astype(np.float32)
                dst_phase.write(phase, 1, window=window)
                del phase

            del output

        # Band descriptions + tags (mirrors write_biomass_cog).
        global_meta = {'ACQUISITION_TIME': acq_time.isoformat(), **metadata}
        dst_amp.set_band_description(1, f"BIOMASS {polarization} - Amplitude")
        dst_amp.update_tags(1, BAND_TYPE='amplitude', ACQUISITION_TIME=acq_time.isoformat(),
                            POLARIZATION=polarization, UNITS='linear amplitude')
        dst_amp.update_tags(**{**global_meta, 'BAND_TYPE': 'amplitude'})

        if include_phase:
            dst_phase.set_band_description(1, f"BIOMASS {polarization} - Phase")
            dst_phase.update_tags(1, BAND_TYPE='phase', ACQUISITION_TIME=acq_time.isoformat(),
                                  POLARIZATION=polarization, UNITS='radians', RANGE='-π to +π')
            dst_phase.update_tags(**{**global_meta, 'BAND_TYPE': 'phase', 'UNITS': 'radians'})

    valid_percent = 100 * valid_count / (width * height)
    print(f"  Valid pixels: {valid_count:,} ({valid_percent:.1f}%)")
    if valid_count == 0:
        print("\n  ⚠ WARNING: 0 valid pixels!")
        print("  This usually means:")
        print("    - DEM doesn't cover the geocoding grid")
        print("    - Or radar data doesn't overlap with the grid")
    elif valid_percent < 10:
        print(f"\n  ⚠ WARNING: Low coverage ({valid_percent:.1f}%)")
        print("  Check that DEM fully covers the geocoding grid")

    print(f"\nWriting COG(s) ({band_desc}): {output_file}")
    finalize_cog(temp_amp, output_file)
    print(f"✓ Created: {output_file} ({output_file.stat().st_size / 1e6:.1f} MB)")
    written = [output_file]
    if include_phase:
        finalize_cog(temp_phase, phase_file)
        print(f"✓ Created: {phase_file} ({phase_file.stat().st_size / 1e6:.1f} MB)")
        written.append(phase_file)

    return written


def write_biomass_cog(output_file, complex_data, grid_params, acq_time, polarization,
                      metadata, phase_file=None):
    """
    Write single-band amplitude and (optionally) phase COGs from complex geocoded data.

    Amplitude and phase are written to *separate* single-band files, mirroring the source
    BIOMASS L1A SCS measurement layout (``*_i_abs.tiff`` / ``*_i_phase.tiff``):
        * ``output_file``: amplitude (linear)
        * ``phase_file``:  phase (radians, -π to +π) — only if ``phase_file`` is given

    The temporary-GeoTIFF write and gdal_translate → COG conversion are delegated to
    :mod:`rift.cogutil` so COG options stay consistent across all rift products.

    Args:
        output_file: Destination amplitude COG path
        phase_file: Destination phase COG path, or None to skip phase output

    Returns:
        list[Path]: Paths of the COG(s) written (amplitude first, then phase if any)
    """
    import gc

    include_phase = phase_file is not None
    band_desc = "amplitude + phase (separate files)" if include_phase else "amplitude only"
    print(f"\nWriting COG(s) ({band_desc}): {output_file}")

    # Extract amplitude (phase discarded unless requested — amplitude is detected last)
    amplitude = np.abs(complex_data).astype(np.float32)

    # Create affine transform (north-up: negative y spacing)
    transform = Affine(
        grid_params['x_posting'], 0.0, grid_params['x_min'],
        0.0, -grid_params['y_posting'], grid_params['y_max']
    )

    profile = base_profile(
        width=grid_params['width'],
        height=grid_params['height'],
        epsg=grid_params['epsg'],
        transform=transform,
        dtype='float32',
        count=1,
        nodata=np.nan,
    )

    amp_bands = {
        1: (amplitude, {
            'BAND_TYPE': 'amplitude',
            'ACQUISITION_TIME': acq_time.isoformat(),
            'POLARIZATION': polarization,
            'UNITS': 'linear amplitude',
        }),
    }
    write_cog(output_file, amp_bands, profile,
              band_descriptions={1: f"BIOMASS {polarization} - Amplitude"},
              global_meta={**metadata, 'BAND_TYPE': 'amplitude'})
    print(f"✓ Created: {output_file} ({output_file.stat().st_size / 1e6:.1f} MB)")

    # Explicitly delete amplitude array to free memory before processing phase
    del amplitude
    gc.collect()

    written = [output_file]

    if include_phase:
        phase = np.angle(complex_data).astype(np.float32)
        phase_bands = {
            1: (phase, {
                'BAND_TYPE': 'phase',
                'ACQUISITION_TIME': acq_time.isoformat(),
                'POLARIZATION': polarization,
                'UNITS': 'radians',
                'RANGE': '-π to +π',
            }),
        }
        write_cog(phase_file, phase_bands, profile,
                  band_descriptions={1: f"BIOMASS {polarization} - Phase"},
                  global_meta={**metadata, 'BAND_TYPE': 'phase', 'UNITS': 'radians'})
        print(f"✓ Created: {phase_file} ({phase_file.stat().st_size / 1e6:.1f} MB)")

        # Explicitly delete phase array to free memory
        del phase
        gc.collect()

        written.append(phase_file)

    return written


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--biomass-granule', required=True, type=Path,
                       help='BIOMASS L1A SCS granule directory or .zip file')
    parser.add_argument('--geogrid', required=True, type=Path,
                       help='JSON file with geogrid parameters')
    parser.add_argument('--dem', required=True, type=Path,
                       help='DEM file in EPSG:3031')
    parser.add_argument('--output', required=True, type=Path,
                       help='Output COG file')
    parser.add_argument('--polarization', default='HH',
                       choices=['HH', 'HV', 'VH', 'VV'],
                       help='Polarization to process (default: HH)')
    parser.add_argument('--amp-only', action='store_true',
                       help='Write amplitude only (default: also write a separate phase COG)')

    args = parser.parse_args()

    # Validate inputs
    if not args.biomass_granule.exists():
        print(f"ERROR: BIOMASS granule not found: {args.biomass_granule}")
        return 1

    if not args.geogrid.exists():
        print(f"ERROR: Geogrid file not found: {args.geogrid}")
        return 1

    if not args.dem.exists():
        print(f"ERROR: DEM file not found: {args.dem}")
        return 1

    print("=" * 70)
    print("BIOMASS GEOCODING TO CUSTOM GRID")
    print("=" * 70)

    # Step 1: Load geogrid parameters
    grid_params = load_geogrid_params(args.geogrid)

    # Step 2: Geocode BIOMASS granule (block-wise) directly to COG(s)
    print("\n" + "=" * 70)
    print("GEOCODING BIOMASS GRANULE")
    print("=" * 70)

    acq_time = extract_acquisition_time(args.biomass_granule)
    metadata = {
        'GEOGRID_SOURCE': str(args.geogrid.name),
        'GRID_EPSG': str(grid_params['epsg']),
        'POSTING': f"{grid_params['x_posting']}m × {grid_params['y_posting']}m",
        'BIOMASS_NATIVE_RESOLUTION': '~6.5m × ~46m (azimuth × range)',
        'POLARIZATION': args.polarization,
        'ACQUISITION_TIME': acq_time.isoformat(),
        'BIOMASS_GRANULE': args.biomass_granule.name,
        'PROCESSING': 'BIOMASS L1A SCS geocoded to custom grid using isce3',
    }

    # Phase file: sibling of the amplitude output with a _phs suffix.
    phase_file = None
    if not args.amp_only:
        stem = args.output.stem
        phase_file = args.output.with_name(f"{stem}_phs{args.output.suffix}")

    geocode_biomass_to_cogs(
        args.biomass_granule,
        args.dem,
        grid_params,
        args.polarization,
        args.output,
        metadata,
        phase_file=phase_file,
    )

    print("\n" + "=" * 70)
    print("COMPLETE!")
    print("=" * 70)

    return 0


if __name__ == '__main__':
    sys.exit(main())
