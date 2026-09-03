#!/usr/bin/env python3
"""
DEM provisioning for the geocoding workflows.

``ensure_dem`` returns a usable DEM path: it uses a caller-supplied DEM if given,
otherwise downloads one covering the granule's footprint via ``sardem`` (NISAR DEM
source). The downloaded DEM stays in EPSG:4326 — ISCE3 reprojects it to EPSG:3031 during
BIOMASS geocoding, and the NISAR workflow does not use a DEM at all.

Ported from the standalone ``download_nisar_dem.py`` prototype (hardcoded paths removed).
The network fetch only happens on the fallback path and requires the sardem data source
to be reachable (a consideration for the MAAP/AWS Batch container).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

import h5py
import yaml
from pyproj import Transformer

FREQ_A_GEOCODE = (
    "/science/LSAR/GSLC/metadata/processingInformation/parameters/"
    "runConfigurationContents"
)


def nisar_bounds_wgs84(nisar_file: Path) -> Tuple[float, float, float, float]:
    """
    Read a NISAR GSLC's output grid bounds and convert to (lon_min, lat_min, lon_max,
    lat_max) in EPSG:4326.
    """
    with h5py.File(nisar_file, "r") as f:
        runconfig = yaml.safe_load(f[FREQ_A_GEOCODE][()].decode("utf-8"))
        geocode = runconfig["runconfig"]["groups"]["processing"]["geocode"]
        x_min = geocode["top_left"]["x_abs"]
        y_max = geocode["top_left"]["y_abs"]
        x_max = geocode["bottom_right"]["x_abs"]
        y_min = geocode["bottom_right"]["y_abs"]
        epsg = geocode["output_epsg"]

    return _corners_to_wgs84(x_min, y_min, x_max, y_max, epsg)


def bbox_to_wgs84(bbox: Dict[str, float], epsg: int = 3031) -> Tuple[float, float, float, float]:
    """Convert an EPSG:3031 bbox dict (x_min/x_max/y_min/y_max) to a WGS84 lon/lat bbox."""
    return _corners_to_wgs84(bbox["x_min"], bbox["y_min"], bbox["x_max"], bbox["y_max"], epsg)


def _corners_to_wgs84(x_min, y_min, x_max, y_max, epsg) -> Tuple[float, float, float, float]:
    transformer = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True)
    corners = [(x_min, y_min), (x_min, y_max), (x_max, y_min), (x_max, y_max)]
    lons, lats = [], []
    for x, y in corners:
        lon, lat = transformer.transform(x, y)
        lons.append(lon)
        lats.append(lat)
    return (min(lons), min(lats), max(lons), max(lats))


def download_dem(bbox_wgs84: Tuple[float, float, float, float], output_file: Path,
                 buffer_deg: float = 0.5, data_source: str = "NISAR") -> Path:
    """
    Download a DEM covering ``bbox_wgs84`` (lon_min, lat_min, lon_max, lat_max) via sardem.

    Args:
        bbox_wgs84: WGS84 bounding box
        output_file: Output DEM path (EPSG:4326)
        buffer_deg: Degrees of margin added on each side
        data_source: sardem data source (default NISAR)

    Returns:
        Path: The downloaded DEM path

    Raises:
        RuntimeError: If sardem fails
    """
    lon_min, lat_min, lon_max, lat_max = bbox_wgs84
    lon_min -= buffer_deg
    lon_max += buffer_deg
    lat_min -= buffer_deg
    lat_max += buffer_deg

    cmd = [
        "sardem",
        "--bbox", str(lon_min), str(lat_min), str(lon_max), str(lat_max),
        "--data-source", data_source,
        "--output", str(output_file),
    ]
    print(f"Downloading DEM via sardem: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"sardem failed (exit {result.returncode}): {result.stderr}")
    print(f"✓ DEM downloaded: {output_file}")
    return Path(output_file)


def ensure_dem(
    dem: Optional[Path] = None,
    *,
    nisar_file: Optional[Path] = None,
    bbox: Optional[Dict[str, float]] = None,
    bbox_epsg: int = 3031,
    workdir: Optional[Path] = None,
    buffer_deg: float = 0.5,
) -> Path:
    """
    Return a usable DEM path, downloading one if not supplied.

    Args:
        dem: Caller-supplied DEM path. If it exists, it is returned unchanged.
        nisar_file: NISAR GSLC HDF5 to derive bounds from (used when ``dem`` is None).
        bbox: EPSG:3031 bbox dict to derive bounds from (alternative to ``nisar_file``).
        bbox_epsg: EPSG of ``bbox`` (default 3031).
        workdir: Directory for the downloaded DEM (default: cwd).
        buffer_deg: Degrees of margin around the footprint.

    Returns:
        Path: DEM path (supplied file, or a freshly downloaded EPSG:4326 DEM).

    Raises:
        ValueError: If no DEM is given and no bounds source is provided.
    """
    if dem is not None and Path(dem).exists():
        print(f"Using provided DEM: {dem}")
        return Path(dem)

    if nisar_file is not None:
        bbox_wgs84 = nisar_bounds_wgs84(Path(nisar_file))
    elif bbox is not None:
        bbox_wgs84 = bbox_to_wgs84(bbox, epsg=bbox_epsg)
    else:
        raise ValueError(
            "ensure_dem: no DEM supplied and no bounds source "
            "(nisar_file or bbox) provided to auto-download."
        )

    workdir = Path(workdir) if workdir else Path.cwd()
    workdir.mkdir(parents=True, exist_ok=True)
    output_file = workdir / "dem_auto_wgs84.tif"
    return download_dem(bbox_wgs84, output_file, buffer_deg=buffer_deg)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Download a DEM for a NISAR GSLC extent.")
    parser.add_argument("nisar_file", type=Path, help="NISAR GSLC HDF5 file")
    parser.add_argument("--output", type=Path, default=Path("dem_auto_wgs84.tif"))
    parser.add_argument("--buffer", type=float, default=0.5, help="Buffer in degrees")
    args = parser.parse_args()

    bbox_wgs84 = nisar_bounds_wgs84(args.nisar_file)
    print(f"Bounds (WGS84): {bbox_wgs84}")
    download_dem(bbox_wgs84, args.output, buffer_deg=args.buffer)
    sys.exit(0)
