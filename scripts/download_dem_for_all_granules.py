#!/usr/bin/env python3
"""
Download a DEM covering all BIOMASS test granules.

This script:
1. Computes the footprint of each BIOMASS granule
2. Computes the union bounding box (in EPSG:3031)
3. Converts to WGS84 and downloads a DEM via sardem
"""

import sys
from pathlib import Path
import argparse

from rift.biomass.geogrid import compute_biomass_footprint
from rift.dem import bbox_to_wgs84, download_dem


def find_biomass_granules(directory):
    """Find all BIOMASS .zip or extracted granule directories."""
    directory = Path(directory)
    granules = []

    # Find .zip files
    for zip_file in directory.glob("BIO_*.zip"):
        granules.append(zip_file)

    # Find extracted directories (if already extracted)
    for granule_dir in directory.glob("BIO_*"):
        if granule_dir.is_dir():
            # Check if there's a corresponding .zip
            zip_file = directory / f"{granule_dir.name}.zip"
            if not zip_file.exists():
                granules.append(granule_dir)

    return sorted(granules)


def compute_union_bbox(granules, polarization='HH'):
    """Compute the union bounding box for all granules."""
    print(f"\nComputing footprints for {len(granules)} granules...")
    print("=" * 70)

    x_mins, x_maxs, y_mins, y_maxs = [], [], [], []

    for i, granule in enumerate(granules, 1):
        print(f"\n[{i}/{len(granules)}] {granule.name}")
        try:
            bbox = compute_biomass_footprint(granule, polarization=polarization)
            x_mins.append(bbox['x_min'])
            x_maxs.append(bbox['x_max'])
            y_mins.append(bbox['y_min'])
            y_maxs.append(bbox['y_max'])
        except Exception as e:
            print(f"  ⚠️  ERROR: {e}")
            print(f"  Skipping this granule...")
            continue

    if not x_mins:
        raise RuntimeError("No granules could be processed!")

    union_bbox = {
        'x_min': min(x_mins),
        'x_max': max(x_maxs),
        'y_min': min(y_mins),
        'y_max': max(y_maxs),
    }

    print("\n" + "=" * 70)
    print("UNION BOUNDING BOX (EPSG:3031)")
    print("=" * 70)
    print(f"  X: [{union_bbox['x_min']:,.0f}, {union_bbox['x_max']:,.0f}] m")
    print(f"  Y: [{union_bbox['y_min']:,.0f}, {union_bbox['y_max']:,.0f}] m")
    print(f"  Width:  {union_bbox['x_max'] - union_bbox['x_min']:,.0f} m")
    print(f"  Height: {union_bbox['y_max'] - union_bbox['y_min']:,.0f} m")

    return union_bbox


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--biomass-dir', type=Path, required=True,
                       help='Directory containing BIOMASS test granules')
    parser.add_argument('--output', type=Path, default=Path('dem_biomass_all.tif'),
                       help='Output DEM file (default: dem_biomass_all.tif)')
    parser.add_argument('--buffer', type=float, default=0.5,
                       help='Buffer in degrees (default: 0.5)')
    parser.add_argument('--polarization', default='HH',
                       choices=['HH', 'HV', 'VH', 'VV'],
                       help='Polarization (default: HH)')

    args = parser.parse_args()

    print("=" * 70)
    print("DOWNLOAD DEM FOR ALL BIOMASS TEST GRANULES")
    print("=" * 70)

    # Find all granules
    granules = find_biomass_granules(args.biomass_dir)
    if not granules:
        print(f"\n❌ ERROR: No BIOMASS granules found in {args.biomass_dir}")
        return 1

    print(f"\nFound {len(granules)} BIOMASS granules:")
    for granule in granules:
        print(f"  - {granule.name}")

    # Compute union bbox
    union_bbox = compute_union_bbox(granules, polarization=args.polarization)

    # Convert to WGS84
    print("\n" + "=" * 70)
    print("CONVERTING TO WGS84")
    print("=" * 70)
    bbox_wgs84 = bbox_to_wgs84(union_bbox, epsg=3031)
    print(f"  Lon: [{bbox_wgs84[0]:.4f}, {bbox_wgs84[2]:.4f}]")
    print(f"  Lat: [{bbox_wgs84[1]:.4f}, {bbox_wgs84[3]:.4f}]")

    # Download DEM
    print("\n" + "=" * 70)
    print("DOWNLOADING DEM VIA SARDEM")
    print("=" * 70)
    dem_path = download_dem(bbox_wgs84, args.output, buffer_deg=args.buffer)

    print("\n" + "=" * 70)
    print("✓ COMPLETE!")
    print("=" * 70)
    print(f"\nDEM saved to: {dem_path}")
    print(f"Size: {dem_path.stat().st_size / 1e6:.1f} MB")
    print(f"\nYou can now use this DEM for all BIOMASS granules with:")
    print(f"  rift biomass process --dem {dem_path} ...")

    return 0


if __name__ == '__main__':
    sys.exit(main())
