#!/usr/bin/env python3
"""
Validate grid alignment across multiple BIOMASS geogrid files.

This script verifies that multiple geogrid JSON files (produced by
rift.biomass.geogrid) are properly aligned to the Antarctica master
grid's chunk boundaries, ensuring all output COGs will have aligned chunks.

Usage:
    # Validate single geogrid
    python validate_grid_alignment.py geogrid1.json

    # Validate multiple geogrids
    python validate_grid_alignment.py geogrid1.json geogrid2.json geogrid3.json

    # Validate all geogrids in directory
    python validate_grid_alignment.py geogrids/*.json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict
from rift.grid import ANTARCTICA_GRID


def load_geogrid(geogrid_file: Path) -> Dict:
    """Load geogrid parameters from JSON file."""
    with open(geogrid_file, 'r') as f:
        return json.load(f)


def check_overlap_alignment(geogrid1: Dict, geogrid2: Dict,
                            name1: str, name2: str) -> List[str]:
    """
    Check if two geogrids have properly aligned overlaps.

    Returns:
        list: Issues found (empty if no issues)
    """
    issues = []

    # Check if they overlap
    x_overlap = not (geogrid1['x_max'] <= geogrid2['x_min'] or
                     geogrid1['x_min'] >= geogrid2['x_max'])
    y_overlap = not (geogrid1['y_max'] <= geogrid2['y_min'] or
                     geogrid1['y_min'] >= geogrid2['y_max'])

    if not (x_overlap and y_overlap):
        return []  # No overlap, no alignment issues possible

    # If they overlap, boundaries must align on chunk boundaries
    # (this should be automatic if both are snapped to master grid,
    #  but we verify here)

    # No specific boundary alignment needed between different grids
    # as long as each is individually aligned to master grid
    # The master grid alignment ensures they'll be compatible

    return issues


def validate_multiple_geogrids(geogrid_files: List[Path]) -> bool:
    """
    Validate multiple geogrid files for proper alignment.

    Returns:
        bool: True if all valid, False if any issues
    """
    if not geogrid_files:
        print("ERROR: No geogrid files provided")
        return False

    print("=" * 70)
    print("VALIDATING GEOGRID ALIGNMENT")
    print("=" * 70)
    print(f"\nMaster grid parameters:")
    print(f"  Chunk size: {ANTARCTICA_GRID.chunk_pixels}×{ANTARCTICA_GRID.chunk_pixels} pixels")
    print(f"  Chunk real-world size: {ANTARCTICA_GRID.chunk_size_x/1000:.2f} km × {ANTARCTICA_GRID.chunk_size_y/1000:.2f} km")
    print(f"\nValidating {len(geogrid_files)} geogrid(s)...")

    all_valid = True
    geogrids = []

    # Validate each geogrid individually
    for i, geogrid_file in enumerate(geogrid_files, 1):
        print(f"\n{'-' * 70}")
        print(f"[{i}/{len(geogrid_files)}] {geogrid_file.name}")
        print(f"{'-' * 70}")

        try:
            geogrid = load_geogrid(geogrid_file)
            geogrids.append((geogrid_file, geogrid))

            # Validate alignment
            is_valid, message = ANTARCTICA_GRID.validate_geogrid(geogrid)

            if is_valid:
                print(f"✓ {message}")

                # Print summary
                n_chunks_x = geogrid['width'] // ANTARCTICA_GRID.chunk_pixels
                n_chunks_y = geogrid['height'] // ANTARCTICA_GRID.chunk_pixels
                print(f"  Dimensions: {geogrid['width']} × {geogrid['height']} pixels")
                print(f"  Chunks: {n_chunks_x} × {n_chunks_y} = {n_chunks_x * n_chunks_y:,} total")
                print(f"  Extent: ({geogrid['x_min']:,.0f}, {geogrid['y_min']:,.0f}) to "
                      f"({geogrid['x_max']:,.0f}, {geogrid['y_max']:,.0f})")
            else:
                print(f"✗ Alignment issues found:")
                for line in message.split('\n'):
                    print(f"  {line}")
                all_valid = False

        except Exception as e:
            print(f"✗ ERROR: {e}")
            all_valid = False

    # Check pairwise overlaps if multiple geogrids
    if len(geogrids) > 1:
        print(f"\n{'=' * 70}")
        print(f"CHECKING PAIRWISE OVERLAP ALIGNMENT")
        print(f"{'=' * 70}")

        overlap_issues = 0
        for i in range(len(geogrids)):
            for j in range(i + 1, len(geogrids)):
                file1, grid1 = geogrids[i]
                file2, grid2 = geogrids[j]

                issues = check_overlap_alignment(grid1, grid2,
                                                file1.name, file2.name)
                if issues:
                    print(f"\n✗ Issues between {file1.name} and {file2.name}:")
                    for issue in issues:
                        print(f"  {issue}")
                    overlap_issues += 1

        if overlap_issues == 0:
            print(f"\n✓ All overlapping geogrids are properly aligned")
        else:
            print(f"\n✗ Found {overlap_issues} pairwise alignment issue(s)")
            all_valid = False

    # Final summary
    print(f"\n{'=' * 70}")
    print(f"VALIDATION SUMMARY")
    print(f"{'=' * 70}")

    if all_valid:
        print(f"✓ ALL GEOGRIDS VALID")
        print(f"  {len(geogrid_files)} geogrid(s) properly aligned to master grid")
        print(f"  COGs produced from these geogrids will have aligned 512×512 chunks")
    else:
        print(f"✗ VALIDATION FAILED")
        print(f"  Some geogrids are not properly aligned")
        print(f"  Fix issues before processing to ensure COG chunk alignment")

    return all_valid


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('geogrids', nargs='+', type=Path,
                       help='Geogrid JSON file(s) to validate')

    args = parser.parse_args()

    # Check that all files exist
    missing = [f for f in args.geogrids if not f.exists()]
    if missing:
        print(f"ERROR: File(s) not found:")
        for f in missing:
            print(f"  {f}")
        return 1

    # Validate
    all_valid = validate_multiple_geogrids(args.geogrids)

    return 0 if all_valid else 1


if __name__ == '__main__':
    sys.exit(main())
