#!/usr/bin/env python3
"""
Geocode a BIOMASS granule to a custom geogrid.

This script geocodes a BIOMASS L1A SCS granule to a user-specified geogrid,
creating a Cloud-Optimized GeoTIFF with amplitude (and optionally phase).

Usage:
    python geocode_biomass_custom_grid.py \
        --biomass-granule /path/to/BIOMASS/scene \
        --geogrid biomass_geogrid.json \
        --dem dem_epsg3031.tif \
        --output biomass_gslc.tif \
        --polarization HH

Arguments:
    --biomass-granule:  BIOMASS L1A SCS granule directory or .zip file
    --geogrid:          JSON file with geogrid parameters (from compute_biomass_geogrid.py)
    --dem:              DEM file in EPSG:3031
    --output:           Output COG file
    --polarization:     Polarization to process (HH, HV, VH, VV)
    --include-phase:    Include phase band in output (default: amplitude only)

Output bands:
    Band 1: Amplitude (linear amplitude of complex SAR signal)
    Band 2: Phase (in radians, range: -π to +π) [only if --include-phase]
"""

import argparse
import sys
import json
from pathlib import Path
from datetime import datetime
import re
import zipfile

import h5py
import yaml
import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.transform import Affine
import subprocess

# Add biomass-reader to path
sys.path.insert(0, str(Path(__file__).parent / "biomass-reader" / "src"))

from biomass_reader import BiomassSlc
import isce3


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

    # Unzip if needed
    if granule_path.suffix == '.zip':
        extract_dir = granule_path.parent / granule_path.stem
        if not extract_dir.exists():
            print(f"  Extracting {granule_path.name}...")
            with zipfile.ZipFile(granule_path, 'r') as zip_ref:
                zip_ref.extractall(granule_path.parent)
        granule_path = extract_dir

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


def write_cog(output_file, complex_data, grid_params, acq_time, polarization, metadata, include_phase=False):
    """
    Write COG (amplitude only or amplitude + phase) from complex geocoded data.

    Band structure:
        Band 1: Amplitude (linear)
        Band 2: Phase (radians, -π to +π) [optional]

    Args:
        include_phase: If True, write both amplitude and phase. If False, only amplitude.
    """
    num_bands = 2 if include_phase else 1
    band_desc = "amplitude + phase" if include_phase else "amplitude only"
    print(f"\nWriting {num_bands}-band GeoTIFF ({band_desc}): {output_file}")

    # Extract amplitude and phase
    amplitude = np.abs(complex_data).astype(np.float32)
    phase = np.angle(complex_data).astype(np.float32)

    # Prepare metadata
    height = grid_params['height']
    width = grid_params['width']

    # Create affine transform
    transform = Affine(
        grid_params['x_posting'], 0.0, grid_params['x_min'],
        0.0, -grid_params['y_posting'], grid_params['y_max']
    )

    # Temporary file
    temp_file = output_file.with_suffix('.temp.tif')

    # Write temporary GeoTIFF
    num_bands = 2 if include_phase else 1
    band_desc = "amplitude + phase" if include_phase else "amplitude"
    print(f"  Writing {num_bands} band(s) ({band_desc}) to temporary file...")

    profile = {
        'driver': 'GTiff',
        'dtype': 'float32',
        'width': width,
        'height': height,
        'count': num_bands,
        'crs': CRS.from_epsg(grid_params['epsg']),
        'transform': transform,
        'nodata': np.nan,
        'tiled': True,
        'blockxsize': 512,
        'blockysize': 512,
        'compress': 'DEFLATE',
    }

    with rasterio.open(temp_file, 'w', **profile) as dst:
        # Write amplitude band
        dst.write(amplitude, 1)
        dst.set_band_description(1, f"BIOMASS {polarization} - Amplitude")
        dst.update_tags(1, **{
            'BAND_TYPE': 'amplitude',
            'ACQUISITION_TIME': acq_time.isoformat(),
            'POLARIZATION': polarization,
            'UNITS': 'linear amplitude',
        })

        # Write phase band if requested
        if include_phase:
            dst.write(phase, 2)
            dst.set_band_description(2, f"BIOMASS {polarization} - Phase")
            dst.update_tags(2, **{
                'BAND_TYPE': 'phase',
                'ACQUISITION_TIME': acq_time.isoformat(),
                'POLARIZATION': polarization,
                'UNITS': 'radians',
                'RANGE': '-π to +π',
            })

        # Global metadata
        dst.update_tags(**metadata)

    print(f"  Converting to Cloud-Optimized GeoTIFF...")
    cmd = [
        'gdal_translate',
        str(temp_file),
        str(output_file),
        '-of', 'COG',
        '-co', 'BLOCKSIZE=512',
        '-co', 'COMPRESS=DEFLATE',
        '-co', 'ZLEVEL=1',
        '-co', 'PREDICTOR=3',
        '-co', 'NUM_THREADS=ALL_CPUS',
        '-co', 'BIGTIFF=YES',
        '-co', 'OVERVIEW_RESAMPLING=AVERAGE',
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gdal_translate failed: {result.stderr}")

    # Remove temporary file
    temp_file.unlink()

    print(f"\n✓ Created: {output_file}")
    band_desc = "amplitude + phase" if include_phase else "amplitude only"
    print(f"  Bands: {num_bands} ({band_desc})")
    print(f"  Size: {output_file.stat().st_size / 1e6:.1f} MB")


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
    parser.add_argument('--include-phase', action='store_true',
                       help='Include phase band in output (default: amplitude only)')

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

    # Step 2: Geocode BIOMASS granule
    print("\n" + "=" * 70)
    print("GEOCODING BIOMASS GRANULE")
    print("=" * 70)

    complex_data, acq_time = geocode_biomass_granule(
        args.biomass_granule,
        args.dem,
        grid_params,
        args.polarization
    )

    # Step 3: Write COG
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

    write_cog(
        args.output,
        complex_data,
        grid_params,
        acq_time,
        args.polarization,
        metadata,
        include_phase=args.include_phase
    )

    print("\n" + "=" * 70)
    print("COMPLETE!")
    print("=" * 70)

    return 0


if __name__ == '__main__':
    sys.exit(main())
