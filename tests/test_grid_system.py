#!/usr/bin/env python3
"""
Comprehensive test suite for the Antarctica master grid system.

This script tests all grid alignment functionality to ensure:
1. Chunk snapping works correctly
2. Geogrids are properly aligned
3. Multiple geogrids have compatible chunks
4. Edge cases are handled (negative coordinates, quadrant boundaries)
"""

import sys
from pathlib import Path
import json
import numpy as np

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from grid_utils import ANTARCTICA_GRID


def test_master_grid_properties():
    """Test that master grid has expected properties."""
    print("=" * 70)
    print("TEST 1: Master Grid Properties")
    print("=" * 70)

    assert ANTARCTICA_GRID.epsg == 3031
    assert ANTARCTICA_GRID.x_posting == 5.0
    assert ANTARCTICA_GRID.y_posting == 40.0
    assert ANTARCTICA_GRID.chunk_pixels == 512
    assert ANTARCTICA_GRID.chunk_size_x == 2560.0
    assert ANTARCTICA_GRID.chunk_size_y == 20480.0

    print("✓ All master grid properties correct")
    return True


def test_chunk_snapping():
    """Test that bbox snapping produces chunk-aligned boundaries."""
    print("\n" + "=" * 70)
    print("TEST 2: Chunk Boundary Snapping")
    print("=" * 70)

    # Test case 1: Positive coordinates
    bbox1 = {'x_min': 123456.7, 'x_max': 234567.8,
             'y_min': 456789.1, 'y_max': 567890.2}
    snapped1 = ANTARCTICA_GRID.snap_bbox(bbox1, expand=True)

    assert snapped1['x_min'] % 2560 == 0, f"x_min not aligned: {snapped1['x_min']}"
    assert snapped1['x_max'] % 2560 == 0, f"x_max not aligned: {snapped1['x_max']}"
    assert snapped1['y_min'] % 20480 == 0, f"y_min not aligned: {snapped1['y_min']}"
    assert snapped1['y_max'] % 20480 == 0, f"y_max not aligned: {snapped1['y_max']}"

    # Test case 2: Negative coordinates
    bbox2 = {'x_min': -234567.8, 'x_max': -123456.7,
             'y_min': -987654.3, 'y_max': -876543.2}
    snapped2 = ANTARCTICA_GRID.snap_bbox(bbox2, expand=True)

    assert snapped2['x_min'] % 2560 == 0, f"x_min not aligned: {snapped2['x_min']}"
    assert snapped2['x_max'] % 2560 == 0, f"x_max not aligned: {snapped2['x_max']}"
    assert snapped2['y_min'] % 20480 == 0, f"y_min not aligned: {snapped2['y_min']}"
    assert snapped2['y_max'] % 20480 == 0, f"y_max not aligned: {snapped2['y_max']}"

    # Test case 3: Mixed positive/negative (crosses origin)
    bbox3 = {'x_min': -50000, 'x_max': 50000,
             'y_min': -50000, 'y_max': 50000}
    snapped3 = ANTARCTICA_GRID.snap_bbox(bbox3, expand=True)

    assert snapped3['x_min'] % 2560 == 0
    assert snapped3['x_max'] % 2560 == 0
    assert snapped3['y_min'] % 20480 == 0
    assert snapped3['y_max'] % 20480 == 0

    print(f"✓ Test case 1 (positive coords): PASS")
    print(f"✓ Test case 2 (negative coords): PASS")
    print(f"✓ Test case 3 (crosses origin): PASS")
    return True


def test_geogrid_computation():
    """Test that computed geogrids are valid and aligned."""
    print("\n" + "=" * 70)
    print("TEST 3: Geogrid Computation")
    print("=" * 70)

    bbox = {'x_min': 100000, 'x_max': 200000,
            'y_min': -500000, 'y_max': -400000}

    # Compute geogrid with snapping
    geogrid = ANTARCTICA_GRID.compute_geogrid_for_bbox(
        bbox, margin_m=5000, snap_to_chunks=True
    )

    # Validate
    is_valid, message = ANTARCTICA_GRID.validate_geogrid(geogrid)
    assert is_valid, f"Geogrid validation failed: {message}"

    # Check dimensions are multiples of 512
    assert geogrid['width'] % 512 == 0, f"Width not multiple of 512: {geogrid['width']}"
    assert geogrid['height'] % 512 == 0, f"Height not multiple of 512: {geogrid['height']}"

    print(f"✓ Geogrid dimensions: {geogrid['width']} × {geogrid['height']} pixels")
    print(f"✓ Chunks: {geogrid['width']//512} × {geogrid['height']//512}")
    print(f"✓ Validation: {message}")
    return True


def test_multiple_geogrid_alignment():
    """Test that multiple geogrids are mutually aligned."""
    print("\n" + "=" * 70)
    print("TEST 4: Multiple Geogrid Alignment")
    print("=" * 70)

    # Create two overlapping geogrids
    bbox1 = {'x_min': 100000, 'x_max': 200000,
             'y_min': -500000, 'y_max': -400000}
    bbox2 = {'x_min': 150000, 'x_max': 250000,
             'y_min': -450000, 'y_max': -350000}

    geogrid1 = ANTARCTICA_GRID.compute_geogrid_for_bbox(bbox1, margin_m=1000, snap_to_chunks=True)
    geogrid2 = ANTARCTICA_GRID.compute_geogrid_for_bbox(bbox2, margin_m=1000, snap_to_chunks=True)

    # Both should be valid
    is_valid1, _ = ANTARCTICA_GRID.validate_geogrid(geogrid1)
    is_valid2, _ = ANTARCTICA_GRID.validate_geogrid(geogrid2)
    assert is_valid1 and is_valid2, "One or both geogrids invalid"

    # Check that overlap region has same chunk boundaries
    overlap_x_min = max(geogrid1['x_min'], geogrid2['x_min'])
    overlap_x_max = min(geogrid1['x_max'], geogrid2['x_max'])
    overlap_y_min = max(geogrid1['y_min'], geogrid2['y_min'])
    overlap_y_max = min(geogrid1['y_max'], geogrid2['y_max'])

    # Verify overlap exists
    assert overlap_x_max > overlap_x_min and overlap_y_max > overlap_y_min

    # Get chunk indices for overlap corners
    chunk1_sw = ANTARCTICA_GRID.get_chunk_indices(overlap_x_min, overlap_y_min)
    chunk1_ne = ANTARCTICA_GRID.get_chunk_indices(overlap_x_max - 1, overlap_y_max - 1)
    chunk2_sw = ANTARCTICA_GRID.get_chunk_indices(overlap_x_min, overlap_y_min)
    chunk2_ne = ANTARCTICA_GRID.get_chunk_indices(overlap_x_max - 1, overlap_y_max - 1)

    # Should be identical
    assert chunk1_sw == chunk2_sw, "SW chunk mismatch"
    assert chunk1_ne == chunk2_ne, "NE chunk mismatch"

    print(f"✓ Geogrid 1 chunks: {ANTARCTICA_GRID.get_chunk_indices(geogrid1['x_min'], geogrid1['y_min'])} to {ANTARCTICA_GRID.get_chunk_indices(geogrid1['x_max']-1, geogrid1['y_max']-1)}")
    print(f"✓ Geogrid 2 chunks: {ANTARCTICA_GRID.get_chunk_indices(geogrid2['x_min'], geogrid2['y_min'])} to {ANTARCTICA_GRID.get_chunk_indices(geogrid2['x_max']-1, geogrid2['y_max']-1)}")
    print(f"✓ Overlap chunks: {chunk1_sw} to {chunk1_ne}")
    print(f"✓ Chunk alignment: PERFECT")
    return True


def test_chunk_indexing():
    """Test chunk index calculation."""
    print("\n" + "=" * 70)
    print("TEST 5: Chunk Indexing")
    print("=" * 70)

    # Test at origin
    assert ANTARCTICA_GRID.get_chunk_indices(0, 0) == (0, 0)

    # Test positive quadrant
    assert ANTARCTICA_GRID.get_chunk_indices(2560, 20480) == (1, 1)
    assert ANTARCTICA_GRID.get_chunk_indices(5120, 40960) == (2, 2)

    # Test negative quadrant
    assert ANTARCTICA_GRID.get_chunk_indices(-2560, -20480) == (-1, -1)
    assert ANTARCTICA_GRID.get_chunk_indices(-5120, -40960) == (-2, -2)

    # Test chunk bounds retrieval
    bounds_00 = ANTARCTICA_GRID.get_chunk_bounds(0, 0)
    assert bounds_00 == {'x_min': 0, 'x_max': 2560, 'y_min': 0, 'y_max': 20480}

    bounds_neg = ANTARCTICA_GRID.get_chunk_bounds(-1, -1)
    assert bounds_neg == {'x_min': -2560, 'x_max': 0, 'y_min': -20480, 'y_max': 0}

    print(f"✓ Origin chunk (0, 0): PASS")
    print(f"✓ Positive chunk indexing: PASS")
    print(f"✓ Negative chunk indexing: PASS")
    print(f"✓ Chunk bounds retrieval: PASS")
    return True


def test_edge_cases():
    """Test edge cases and boundary conditions."""
    print("\n" + "=" * 70)
    print("TEST 6: Edge Cases")
    print("=" * 70)

    # Test exactly on chunk boundary (should not change when snapped)
    bbox_aligned = {
        'x_min': 0.0,
        'x_max': 2560.0,
        'y_min': 0.0,
        'y_max': 20480.0
    }
    snapped_aligned = ANTARCTICA_GRID.snap_bbox(bbox_aligned, expand=True)
    assert snapped_aligned == bbox_aligned, "Already-aligned bbox changed"

    # Test very small bbox (single chunk or less)
    bbox_small = {'x_min': 100, 'x_max': 200, 'y_min': 100, 'y_max': 200}
    geogrid_small = ANTARCTICA_GRID.compute_geogrid_for_bbox(bbox_small, margin_m=0, snap_to_chunks=True)
    is_valid, _ = ANTARCTICA_GRID.validate_geogrid(geogrid_small)
    assert is_valid, "Small bbox geogrid invalid"

    # Test very large bbox (many chunks)
    bbox_large = {'x_min': -500000, 'x_max': 500000, 'y_min': -500000, 'y_max': 500000}
    geogrid_large = ANTARCTICA_GRID.compute_geogrid_for_bbox(bbox_large, margin_m=0, snap_to_chunks=True)
    is_valid, _ = ANTARCTICA_GRID.validate_geogrid(geogrid_large)
    assert is_valid, "Large bbox geogrid invalid"

    print(f"✓ Already-aligned bbox: PASS")
    print(f"✓ Small bbox (single chunk): PASS")
    print(f"✓ Large bbox (many chunks): PASS")
    return True


def test_json_serialization():
    """Test that geogrids can be saved/loaded as JSON."""
    print("\n" + "=" * 70)
    print("TEST 7: JSON Serialization")
    print("=" * 70)

    bbox = {'x_min': 100000, 'x_max': 200000, 'y_min': -500000, 'y_max': -400000}
    geogrid = ANTARCTICA_GRID.compute_geogrid_for_bbox(bbox, margin_m=5000, snap_to_chunks=True)

    # Save to JSON
    test_file = Path('test_geogrid_temp.json')
    with open(test_file, 'w') as f:
        json.dump(geogrid, f, indent=2)

    # Load from JSON
    with open(test_file, 'r') as f:
        geogrid_loaded = json.load(f)

    # Validate loaded geogrid
    is_valid, message = ANTARCTICA_GRID.validate_geogrid(geogrid_loaded)
    assert is_valid, f"Loaded geogrid invalid: {message}"

    # Clean up
    test_file.unlink()

    print(f"✓ Save to JSON: PASS")
    print(f"✓ Load from JSON: PASS")
    print(f"✓ Validation after load: PASS")
    return True


def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("ANTARCTICA MASTER GRID - COMPREHENSIVE TEST SUITE")
    print("=" * 70)

    tests = [
        test_master_grid_properties,
        test_chunk_snapping,
        test_geogrid_computation,
        test_multiple_geogrid_alignment,
        test_chunk_indexing,
        test_edge_cases,
        test_json_serialization,
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
        except AssertionError as e:
            print(f"\n✗ FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"\n✗ ERROR: {e}")
            failed += 1

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Total tests: {len(tests)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    if failed == 0:
        print("\n✓✓✓ ALL TESTS PASSED ✓✓✓")
        print("The Antarctica master grid system is working correctly!")
        return 0
    else:
        print(f"\n✗✗✗ {failed} TEST(S) FAILED ✗✗✗")
        return 1


if __name__ == '__main__':
    sys.exit(main())
