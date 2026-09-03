#!/usr/bin/env python3
"""
Compute optimal geogrid parameters for a BIOMASS granule.

This script analyzes a BIOMASS granule's radar footprint and computes
appropriate geogrid parameters in EPSG:3031 (Antarctic Polar Stereographic).

The computed geogrid is snapped to the Antarctica master grid's chunk boundaries
to ensure all processed granules produce COGs with aligned 512×512 chunks.
"""

import sys
import zipfile
from pathlib import Path
import argparse
import json

from biomass_reader import BiomassSlc
import isce3
import numpy as np

from rift.grid import ANTARCTICA_GRID, AntarcticaGrid


def ensure_granule_dir(granule_path):
    """
    Return a BIOMASS granule directory, extracting the .zip alongside it if needed.

    ``biomass_reader.BiomassSlc.from_dir`` requires a directory, so any .zip input is
    extracted once (into the same parent) and the resulting directory is returned. This
    is shared by both footprint computation and geocoding so either entry point accepts
    a .zip or a directory.
    """
    granule_path = Path(granule_path)
    if granule_path.suffix == '.zip':
        extract_dir = granule_path.parent / granule_path.stem
        if not extract_dir.exists():
            print(f"  Extracting {granule_path.name}...")
            with zipfile.ZipFile(granule_path, 'r') as zip_ref:
                zip_ref.extractall(granule_path.parent)
        return extract_dir
    return granule_path


def compute_biomass_footprint(granule_path, polarization='HH', samples_per_edge=10):
    """
    Compute the geographic footprint of a BIOMASS granule.

    Accepts a granule directory or .zip.

    Returns:
        dict: Bounding box in EPSG:3031 with keys x_min, x_max, y_min, y_max
    """
    granule_path = ensure_granule_dir(granule_path)
    print(f"Computing footprint for: {granule_path}")

    # Load BIOMASS SLC
    slc = BiomassSlc.from_dir(granule_path, polarization=polarization)
    rg = slc.radar_grid
    orbit = slc.orbit
    doppler = slc.doppler

    print(f"  Radar grid: {rg.length} × {rg.width} pixels")

    # Projection for EPSG:3031
    proj = isce3.core.make_projection(3031)
    dem_interp = isce3.geometry.DEMInterpolator(0.0)  # Assume 0 height

    # Sample perimeter points
    x_coords = []
    y_coords = []

    # Compute sensing times
    sensing_end = rg.sensing_start + (rg.length - 1) * (1.0 / rg.prf)

    # Top edge (near range to far range at start)
    for i in range(samples_per_edge):
        frac = i / (samples_per_edge - 1)
        sr = rg.starting_range + frac * (rg.end_range - rg.starting_range)
        azt = rg.sensing_start

        llh = isce3.geometry.rdr2geo(azt, sr, orbit, rg.lookside,
                                      doppler.eval(azt, sr), rg.wavelength, dem_interp)
        xyz = proj.forward(llh)
        x_coords.append(xyz[0])
        y_coords.append(xyz[1])

    # Right edge (far range, start to end)
    for i in range(samples_per_edge):
        frac = i / (samples_per_edge - 1)
        azt = rg.sensing_start + frac * (sensing_end - rg.sensing_start)
        sr = rg.end_range

        llh = isce3.geometry.rdr2geo(azt, sr, orbit, rg.lookside,
                                      doppler.eval(azt, sr), rg.wavelength, dem_interp)
        xyz = proj.forward(llh)
        x_coords.append(xyz[0])
        y_coords.append(xyz[1])

    # Bottom edge (far range to near range at end)
    for i in range(samples_per_edge):
        frac = i / (samples_per_edge - 1)
        sr = rg.end_range - frac * (rg.end_range - rg.starting_range)
        azt = sensing_end

        llh = isce3.geometry.rdr2geo(azt, sr, orbit, rg.lookside,
                                      doppler.eval(azt, sr), rg.wavelength, dem_interp)
        xyz = proj.forward(llh)
        x_coords.append(xyz[0])
        y_coords.append(xyz[1])

    # Left edge (near range, end to start)
    for i in range(samples_per_edge):
        frac = i / (samples_per_edge - 1)
        azt = sensing_end - frac * (sensing_end - rg.sensing_start)
        sr = rg.starting_range

        llh = isce3.geometry.rdr2geo(azt, sr, orbit, rg.lookside,
                                      doppler.eval(azt, sr), rg.wavelength, dem_interp)
        xyz = proj.forward(llh)
        x_coords.append(xyz[0])
        y_coords.append(xyz[1])

    # Compute bounding box
    bbox = {
        'x_min': min(x_coords),
        'x_max': max(x_coords),
        'y_min': min(y_coords),
        'y_max': max(y_coords),
    }

    print(f"\nFootprint (EPSG:3031):")
    print(f"  X: [{bbox['x_min']:,.0f}, {bbox['x_max']:,.0f}] m")
    print(f"  Y: [{bbox['y_min']:,.0f}, {bbox['y_max']:,.0f}] m")
    print(f"  Width:  {bbox['x_max'] - bbox['x_min']:,.0f} m")
    print(f"  Height: {bbox['y_max'] - bbox['y_min']:,.0f} m")

    return bbox


def create_geogrid_params(bbox, margin_m=5000, snap_to_master_grid=True, grid=None):
    """
    Create geogrid parameters covering the bounding box.

    Args:
        bbox: Bounding box dict with x_min, x_max, y_min, y_max
        margin_m: Margin to add around bbox (meters)
        snap_to_master_grid: If True, snap to Antarctica master grid chunk boundaries
        grid: AntarcticaGrid instance defining spacing/chunks (default: ANTARCTICA_GRID,
              i.e. 5×5). Pass ``ANTARCTICA_GRID.with_spacing(5, 40)`` for BIOMASS-native.

    Returns:
        dict: Geogrid parameters
    """
    if grid is None:
        grid = ANTARCTICA_GRID
    # Add margin
    bbox_with_margin = {
        'x_min': bbox['x_min'] - margin_m,
        'x_max': bbox['x_max'] + margin_m,
        'y_min': bbox['y_min'] - margin_m,
        'y_max': bbox['y_max'] + margin_m,
    }

    print(f"\nBounding box with {margin_m}m margin:")
    print(f"  X: [{bbox_with_margin['x_min']:,.0f}, {bbox_with_margin['x_max']:,.0f}] m")
    print(f"  Y: [{bbox_with_margin['y_min']:,.0f}, {bbox_with_margin['y_max']:,.0f}] m")

    # Snap to master grid chunk boundaries
    if snap_to_master_grid:
        print(f"\nSnapping to master grid (512×512 chunk boundaries)...")
        snapped_bbox = grid.snap_bbox(bbox_with_margin, expand=True)
        print(f"  Snapped X: [{snapped_bbox['x_min']:,.0f}, {snapped_bbox['x_max']:,.0f}] m")
        print(f"  Snapped Y: [{snapped_bbox['y_min']:,.0f}, {snapped_bbox['y_max']:,.0f}] m")
        bbox_with_margin = snapped_bbox

    # Compute geogrid using master grid
    geogrid = grid.compute_geogrid_for_bbox(
        bbox_with_margin,
        margin_m=0,  # Margin already added above
        snap_to_chunks=False  # Already snapped above
    )

    # Print detailed info
    grid.print_geogrid_info(geogrid)

    # Memory estimate
    total_pixels = geogrid['width'] * geogrid['height']
    print(f"\nMemory estimate:")
    print(f"  Complex64: {total_pixels * 8 / 1e9:.2f} GB")
    print(f"  Float32 (amplitude or phase): {total_pixels * 4 / 1e9:.2f} GB")

    return geogrid


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('granule', type=Path,
                       help='BIOMASS granule directory or .zip file')
    parser.add_argument('--polarization', default='HH',
                       choices=['HH', 'HV', 'VH', 'VV'],
                       help='Polarization (default: HH)')
    parser.add_argument('--margin', type=float, default=5000.0,
                       help='Margin around footprint in meters (default: 5000m)')
    parser.add_argument('--x-spacing', type=float, default=5.0,
                       help='Master grid X (azimuth) spacing in meters (default: 5)')
    parser.add_argument('--y-spacing', type=float, default=5.0,
                       help='Master grid Y (range) spacing in meters (default: 5)')
    parser.add_argument('--native', action='store_true',
                       help='Use BIOMASS-native spacing 5×40 (overrides --x/--y-spacing)')
    parser.add_argument('--no-snap', action='store_true',
                       help='Do not snap to master grid chunk boundaries (not recommended)')
    parser.add_argument('--output', type=Path, default=Path('biomass_geogrid.json'),
                       help='Output JSON file (default: biomass_geogrid.json)')

    args = parser.parse_args()

    if args.native:
        grid = ANTARCTICA_GRID.with_spacing(5.0, 40.0)
    else:
        grid = ANTARCTICA_GRID.with_spacing(args.x_spacing, args.y_spacing)

    print("=" * 70)
    print("BIOMASS GEOGRID COMPUTATION")
    print("=" * 70)
    print()

    if args.no_snap:
        print("⚠️  WARNING: Snapping to master grid is DISABLED")
        print("   Output COGs may not align with other granules!\n")

    # Compute footprint
    bbox = compute_biomass_footprint(args.granule, args.polarization)

    # Create geogrid (snapped to master grid by default)
    geogrid = create_geogrid_params(bbox, args.margin, snap_to_master_grid=not args.no_snap,
                                    grid=grid)

    # Save to JSON
    with open(args.output, 'w') as f:
        json.dump(geogrid, f, indent=2)

    print(f"\n{'=' * 70}")
    print(f"✓ Saved geogrid parameters to: {args.output}")
    print(f"{'=' * 70}")

    if not args.no_snap:
        print("\n✓ Grid is aligned to Antarctica master grid")
        print("  All COGs processed with this geogrid will have aligned 512×512 chunks")

    return 0


if __name__ == '__main__':
    sys.exit(main())
