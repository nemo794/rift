#!/usr/bin/env python3
"""
Grid utilities for Antarctica master grid alignment.

This module provides the AntarcticaGrid dataclass and utilities to snap arbitrary
bounding boxes to the Antarctica master grid's chunk boundaries, ensuring all
BIOMASS granules processed with geocode_biomass_custom_grid.py produce COGs with
aligned 512×512 chunks.

The master grid uses:
- EPSG:3031 (Antarctic Polar Stereographic)
- Pixel spacing: 5m × 40m
- COG chunk size: 512×512 pixels = 2,560m × 20,480m real-world tiles
- Origin: (0, 0) at South Pole
- Extent: ±3,072,000 m (covers entire Antarctic continent)
"""

import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Tuple
import numpy as np


@dataclass(frozen=True)
class AntarcticaGrid:
    """
    Antarctica master reference grid for BIOMASS processing.

    This grid defines chunk boundaries for the entire Antarctic continent,
    ensuring all processed BIOMASS granules produce COGs with aligned chunks.

    All parameters are immutable (frozen=True) to prevent accidental modification.
    """

    # Projection and pixel spacing
    epsg: int = 3031
    x_posting: float = 5.0      # meters (azimuth direction)
    y_posting: float = 40.0     # meters (range direction)

    # COG chunk configuration
    chunk_pixels: int = 512     # 512×512 pixel chunks

    # Master grid extent (covers entire Antarctica)
    x_min: float = -3_072_000.0  # meters
    x_max: float = 3_072_000.0   # meters
    y_min: float = -3_072_000.0  # meters
    y_max: float = 3_072_000.0   # meters

    # Origin (South Pole in EPSG:3031)
    origin_x: float = 0.0
    origin_y: float = 0.0

    @property
    def chunk_size_x(self) -> float:
        """Real-world X size of one chunk in meters."""
        return self.chunk_pixels * self.x_posting  # 2,560 m

    @property
    def chunk_size_y(self) -> float:
        """Real-world Y size of one chunk in meters."""
        return self.chunk_pixels * self.y_posting  # 20,480 m

    @property
    def width(self) -> int:
        """Total grid width in pixels (rarely used - individual granules use subsets)."""
        return int((self.x_max - self.x_min) / self.x_posting)

    @property
    def height(self) -> int:
        """Total grid height in pixels (rarely used - individual granules use subsets)."""
        return int((self.y_max - self.y_min) / self.y_posting)

    @property
    def n_chunks_x(self) -> int:
        """Total number of chunks in X direction."""
        return self.width // self.chunk_pixels

    @property
    def n_chunks_y(self) -> int:
        """Total number of chunks in Y direction."""
        return self.height // self.chunk_pixels

    def snap_coordinate(self, value: float, chunk_size: float, mode: str = 'floor') -> float:
        """
        Snap a coordinate to the nearest chunk boundary.

        Args:
            value: Coordinate value in meters
            chunk_size: Chunk size in meters (self.chunk_size_x or self.chunk_size_y)
            mode: 'floor' (snap down) or 'ceil' (snap up)

        Returns:
            float: Snapped coordinate aligned to chunk boundary from origin (0, 0)
        """
        if mode == 'floor':
            return np.floor(value / chunk_size) * chunk_size
        elif mode == 'ceil':
            return np.ceil(value / chunk_size) * chunk_size
        else:
            raise ValueError(f"Invalid mode: {mode}. Use 'floor' or 'ceil'")

    def snap_bbox(self, bbox: Dict[str, float], expand: bool = True) -> Dict[str, float]:
        """
        Snap a bounding box to master grid chunk boundaries.

        Args:
            bbox: Bounding box with keys: x_min, x_max, y_min, y_max (meters, EPSG:3031)
            expand: If True, expand bbox to cover entire chunks (floor min, ceil max).
                   If False, contract bbox to fit within chunks (ceil min, floor max).

        Returns:
            dict: Snapped bounding box with same keys, aligned to chunk boundaries
        """
        if expand:
            # Expand: floor minimums, ceil maximums
            x_min_snapped = self.snap_coordinate(bbox['x_min'], self.chunk_size_x, 'floor')
            x_max_snapped = self.snap_coordinate(bbox['x_max'], self.chunk_size_x, 'ceil')
            y_min_snapped = self.snap_coordinate(bbox['y_min'], self.chunk_size_y, 'floor')
            y_max_snapped = self.snap_coordinate(bbox['y_max'], self.chunk_size_y, 'ceil')
        else:
            # Contract: ceil minimums, floor maximums
            x_min_snapped = self.snap_coordinate(bbox['x_min'], self.chunk_size_x, 'ceil')
            x_max_snapped = self.snap_coordinate(bbox['x_max'], self.chunk_size_x, 'floor')
            y_min_snapped = self.snap_coordinate(bbox['y_min'], self.chunk_size_y, 'ceil')
            y_max_snapped = self.snap_coordinate(bbox['y_max'], self.chunk_size_y, 'floor')

        return {
            'x_min': x_min_snapped,
            'x_max': x_max_snapped,
            'y_min': y_min_snapped,
            'y_max': y_max_snapped,
        }

    def compute_geogrid_for_bbox(self,
                                  bbox: Dict[str, float],
                                  margin_m: float = 0.0,
                                  snap_to_chunks: bool = True) -> Dict:
        """
        Compute geogrid parameters from a bounding box.

        Args:
            bbox: Bounding box with keys: x_min, x_max, y_min, y_max
            margin_m: Margin to add around bbox before snapping (meters)
            snap_to_chunks: If True, snap bbox to chunk boundaries (recommended)

        Returns:
            dict: Geogrid parameters compatible with geocode_biomass_custom_grid.py
        """
        # Add margin
        bbox_with_margin = {
            'x_min': bbox['x_min'] - margin_m,
            'x_max': bbox['x_max'] + margin_m,
            'y_min': bbox['y_min'] - margin_m,
            'y_max': bbox['y_max'] + margin_m,
        }

        # Snap to chunks if requested
        if snap_to_chunks:
            bbox_final = self.snap_bbox(bbox_with_margin, expand=True)
        else:
            bbox_final = bbox_with_margin

        # Compute dimensions
        width = int((bbox_final['x_max'] - bbox_final['x_min']) / self.x_posting)
        height = int((bbox_final['y_max'] - bbox_final['y_min']) / self.y_posting)

        geogrid = {
            'epsg': self.epsg,
            'x_min': bbox_final['x_min'],
            'x_max': bbox_final['x_max'],
            'y_min': bbox_final['y_min'],
            'y_max': bbox_final['y_max'],
            'x_posting': self.x_posting,
            'y_posting': self.y_posting,
            'width': width,
            'height': height,
        }

        return geogrid

    def compute_geogrid_for_granule(self,
                                     granule_path: Path,
                                     polarization: str = 'HH',
                                     margin_m: float = 5000.0,
                                     snap_to_chunks: bool = True) -> Dict:
        """
        Compute chunk-aligned geogrid directly from a BIOMASS granule.

        This is a high-level convenience method that:
        1. Computes the granule's radar footprint in EPSG:3031
        2. Adds margin
        3. Snaps to master grid chunk boundaries
        4. Returns geogrid parameters ready for geocoding

        Args:
            granule_path: Path to BIOMASS granule directory or .zip file
            polarization: Polarization to use for footprint computation
            margin_m: Margin to add around footprint (meters)
            snap_to_chunks: If True, snap to chunk boundaries (recommended)

        Returns:
            dict: Geogrid parameters compatible with geocode_biomass_custom_grid.py
        """
        # Import here to avoid circular dependency
        from compute_biomass_geogrid import compute_biomass_footprint

        # Compute footprint
        bbox = compute_biomass_footprint(granule_path, polarization)

        # Compute geogrid with margin and snapping
        return self.compute_geogrid_for_bbox(bbox, margin_m=margin_m, snap_to_chunks=snap_to_chunks)

    def get_chunk_indices(self, x: float, y: float) -> Tuple[int, int]:
        """
        Get chunk indices for a coordinate.

        Args:
            x: X coordinate in meters (EPSG:3031)
            y: Y coordinate in meters (EPSG:3031)

        Returns:
            tuple: (chunk_x, chunk_y) indices relative to origin (0, 0)
                   Negative indices are valid for coordinates in negative quadrants
        """
        chunk_x = int(np.floor(x / self.chunk_size_x))
        chunk_y = int(np.floor(y / self.chunk_size_y))
        return (chunk_x, chunk_y)

    def get_chunk_bounds(self, chunk_x: int, chunk_y: int) -> Dict[str, float]:
        """
        Get bounding box for a specific chunk.

        Args:
            chunk_x: Chunk index in X direction
            chunk_y: Chunk index in Y direction

        Returns:
            dict: Bounding box with keys: x_min, x_max, y_min, y_max
        """
        return {
            'x_min': chunk_x * self.chunk_size_x,
            'x_max': (chunk_x + 1) * self.chunk_size_x,
            'y_min': chunk_y * self.chunk_size_y,
            'y_max': (chunk_y + 1) * self.chunk_size_y,
        }

    def validate_geogrid(self, geogrid: Dict) -> Tuple[bool, str]:
        """
        Validate that a geogrid is properly aligned to master grid chunks.

        Args:
            geogrid: Geogrid parameters dict

        Returns:
            tuple: (is_valid, message)
        """
        issues = []

        # Check EPSG
        if geogrid.get('epsg') != self.epsg:
            issues.append(f"EPSG mismatch: expected {self.epsg}, got {geogrid.get('epsg')}")

        # Check posting
        if geogrid.get('x_posting') != self.x_posting:
            issues.append(f"X posting mismatch: expected {self.x_posting}m, got {geogrid.get('x_posting')}m")
        if geogrid.get('y_posting') != self.y_posting:
            issues.append(f"Y posting mismatch: expected {self.y_posting}m, got {geogrid.get('y_posting')}m")

        # Check chunk alignment
        x_min = geogrid.get('x_min', 0)
        x_max = geogrid.get('x_max', 0)
        y_min = geogrid.get('y_min', 0)
        y_max = geogrid.get('y_max', 0)

        # Check if boundaries align to chunks
        if abs(x_min % self.chunk_size_x) > 1e-6:
            issues.append(f"x_min ({x_min:.1f}m) not aligned to chunk boundary ({self.chunk_size_x}m)")
        if abs(x_max % self.chunk_size_x) > 1e-6:
            issues.append(f"x_max ({x_max:.1f}m) not aligned to chunk boundary ({self.chunk_size_x}m)")
        if abs(y_min % self.chunk_size_y) > 1e-6:
            issues.append(f"y_min ({y_min:.1f}m) not aligned to chunk boundary ({self.chunk_size_y}m)")
        if abs(y_max % self.chunk_size_y) > 1e-6:
            issues.append(f"y_max ({y_max:.1f}m) not aligned to chunk boundary ({self.chunk_size_y}m)")

        # Check dimensions
        expected_width = int((x_max - x_min) / self.x_posting)
        expected_height = int((y_max - y_min) / self.y_posting)

        if geogrid.get('width') != expected_width:
            issues.append(f"Width mismatch: expected {expected_width}, got {geogrid.get('width')}")
        if geogrid.get('height') != expected_height:
            issues.append(f"Height mismatch: expected {expected_height}, got {geogrid.get('height')}")

        # Check that dimensions are multiples of chunk size
        if geogrid.get('width', 0) % self.chunk_pixels != 0:
            issues.append(f"Width ({geogrid.get('width')}) not a multiple of chunk size ({self.chunk_pixels} pixels)")
        if geogrid.get('height', 0) % self.chunk_pixels != 0:
            issues.append(f"Height ({geogrid.get('height')}) not a multiple of chunk size ({self.chunk_pixels} pixels)")

        if issues:
            return (False, "\n".join(issues))
        else:
            return (True, "Grid properly aligned to master grid chunks")

    def print_geogrid_info(self, geogrid: Dict):
        """
        Print human-readable grid information with chunk alignment details.

        Args:
            geogrid: Geogrid parameters dict
        """
        print("\nGeogrid Information:")
        print(f"  EPSG: {geogrid['epsg']}")
        print(f"  Posting: {geogrid['x_posting']}m × {geogrid['y_posting']}m")
        print(f"  Dimensions: {geogrid['width']} × {geogrid['height']} pixels")
        print(f"  Extent (EPSG:3031):")
        print(f"    X: [{geogrid['x_min']:,.0f}, {geogrid['x_max']:,.0f}] m")
        print(f"    Y: [{geogrid['y_min']:,.0f}, {geogrid['y_max']:,.0f}] m")
        print(f"  Real-world size:")
        print(f"    Width:  {(geogrid['x_max'] - geogrid['x_min']) / 1000:.2f} km")
        print(f"    Height: {(geogrid['y_max'] - geogrid['y_min']) / 1000:.2f} km")

        # Chunk info
        n_chunks_x = geogrid['width'] // self.chunk_pixels
        n_chunks_y = geogrid['height'] // self.chunk_pixels
        print(f"\nCOG Chunk Information:")
        print(f"  Chunk size: {self.chunk_pixels}×{self.chunk_pixels} pixels = {self.chunk_size_x/1000:.2f}×{self.chunk_size_y/1000:.2f} km")
        print(f"  Number of chunks: {n_chunks_x} × {n_chunks_y} = {n_chunks_x * n_chunks_y:,} total")

        # Corner chunks
        sw_chunk = self.get_chunk_indices(geogrid['x_min'], geogrid['y_min'])
        ne_chunk = self.get_chunk_indices(geogrid['x_max'] - 1, geogrid['y_max'] - 1)
        print(f"  Chunk indices range:")
        print(f"    X: [{sw_chunk[0]}, {ne_chunk[0]}]")
        print(f"    Y: [{sw_chunk[1]}, {ne_chunk[1]}]")

        # Validation
        is_valid, message = self.validate_geogrid(geogrid)
        if is_valid:
            print(f"\n✓ {message}")
        else:
            print(f"\n✗ Grid alignment issues:")
            print(f"  {message}")

    def print_info(self):
        """Print information about the master grid."""
        print("=" * 70)
        print("ANTARCTICA MASTER GRID")
        print("=" * 70)
        print(f"\nProjection:")
        print(f"  EPSG: {self.epsg} (Antarctic Polar Stereographic)")
        print(f"  Origin: ({self.origin_x:.0f}, {self.origin_y:.0f}) at South Pole")

        print(f"\nPixel Spacing:")
        print(f"  X (azimuth): {self.x_posting}m")
        print(f"  Y (range):   {self.y_posting}m")

        print(f"\nCOG Chunk Configuration:")
        print(f"  Chunk size: {self.chunk_pixels}×{self.chunk_pixels} pixels")
        print(f"  Real-world X: {self.chunk_size_x/1000:.2f} km ({self.chunk_size_x:.0f} m)")
        print(f"  Real-world Y: {self.chunk_size_y/1000:.2f} km ({self.chunk_size_y:.0f} m)")

        print(f"\nMaster Grid Extent:")
        print(f"  X: [{self.x_min:,.0f}, {self.x_max:,.0f}] m")
        print(f"  Y: [{self.y_min:,.0f}, {self.y_max:,.0f}] m")
        print(f"  Coverage: {(self.x_max - self.x_min)/1000:.0f} km × {(self.y_max - self.y_min)/1000:.0f} km")

        print(f"\nTotal Grid Dimensions (full Antarctica):")
        print(f"  Pixels: {self.width:,} × {self.height:,}")
        print(f"  Chunks: {self.n_chunks_x:,} × {self.n_chunks_y:,} = {self.n_chunks_x * self.n_chunks_y:,} total")
        print(f"  Note: Individual granules use small subsets of this grid")

        print(f"\nAlignment Guarantee:")
        print(f"  All granule extents snap to chunk boundaries")
        print(f"  → Perfect COG alignment across all processing")


# Singleton instance - this is what users import and use
ANTARCTICA_GRID = AntarcticaGrid()


if __name__ == '__main__':
    # Example usage
    ANTARCTICA_GRID.print_info()

    print("\n" + "=" * 70)
    print("EXAMPLE: Snap granule footprint to chunk boundaries")
    print("=" * 70)

    example_bbox = {
        'x_min': 123456.7,
        'x_max': 234567.8,
        'y_min': -987654.3,
        'y_max': -876543.2,
    }

    print("\nOriginal granule footprint:")
    print(f"  X: [{example_bbox['x_min']:,.1f}, {example_bbox['x_max']:,.1f}] m")
    print(f"  Y: [{example_bbox['y_min']:,.1f}, {example_bbox['y_max']:,.1f}] m")

    snapped_bbox = ANTARCTICA_GRID.snap_bbox(example_bbox, expand=True)
    print("\nSnapped to chunk boundaries:")
    print(f"  X: [{snapped_bbox['x_min']:,.1f}, {snapped_bbox['x_max']:,.1f}] m")
    print(f"  Y: [{snapped_bbox['y_min']:,.1f}, {snapped_bbox['y_max']:,.1f}] m")

    # Create geogrid
    geogrid = ANTARCTICA_GRID.compute_geogrid_for_bbox(example_bbox, margin_m=0, snap_to_chunks=True)
    ANTARCTICA_GRID.print_geogrid_info(geogrid)
