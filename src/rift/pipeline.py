#!/usr/bin/env python3
"""
Per-granule orchestration for the two end-to-end workflows.

``rift`` exposes two independent end-to-end workflows — one for BIOMASS, one for NISAR.
They are **not** combined (there is no fusion step yet; that is a later phase). Each
workflow runs within a single MAAP DPS job: cross-granule fan-out, scheduling, and
retries are the platform's responsibility, not this module's.

Structure:
    * ``biomass_to_cogs`` / ``nisar_to_cogs`` — sensor amplitude COGs (always written).
    * ``infer_cogs`` — placeholder threshold → binary-mask COGs.
    * ``run_biomass_end_to_end`` / ``run_nisar_end_to_end`` — full chains that write the
      final products (and a resolved-config JSON) to ``output_dir``. Intermediate
      amplitude COGs are deleted by default (``keep_intermediates=False``) to minimize
      egress; pass ``keep_intermediates=True`` to keep them in ``output_dir``.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from rift.grid import ANTARCTICA_GRID, AntarcticaGrid


# --------------------------------------------------------------------------------------
# Grid helpers
# --------------------------------------------------------------------------------------

def _biomass_grid(x_spacing: float, y_spacing: float, native: bool) -> AntarcticaGrid:
    """BIOMASS grid: native → 5×40, else the requested spacing (default 5×5)."""
    if native:
        return ANTARCTICA_GRID.with_spacing(5.0, 40.0)
    return ANTARCTICA_GRID.with_spacing(x_spacing, y_spacing)


# --------------------------------------------------------------------------------------
# Per-step functions (always write their COGs; no keep/delete policy here)
# --------------------------------------------------------------------------------------

def biomass_to_cogs(granule: Path, dem: Path, output_dir: Path, *,
                    grid: AntarcticaGrid = ANTARCTICA_GRID,
                    pols: Optional[List[str]] = None, margin: float = 5000.0,
                    polarization_for_footprint: str = "HH",
                    amp_only: bool = False) -> List[Path]:
    """
    Geocode a BIOMASS granule to amplitude (and phase) COGs (one each per polarization).

    footprint → margin → snap-to-chunks geogrid → ISCE3 geocode_slc (complex) →
    |·| amplitude COG (+ angle phase COG unless ``amp_only``).

    Args:
        granule: Path to BIOMASS L1A SCS granule directory or .zip file
        dem: Path to DEM file
        output_dir: Output directory for COG files
        grid: Target grid (default: ANTARCTICA_GRID)
        pols: Polarizations to process (default: None = all available polarizations)
        margin: Margin in meters to add around footprint (default: 5000.0)
        polarization_for_footprint: Polarization to use for footprint computation (default: "HH")
        amp_only: Write amplitude only (default: also write a separate phase COG per pol)

    Returns:
        List of paths to created COG files (amplitude and, unless amp_only, phase)
    """
    from rift.biomass.geogrid import compute_biomass_footprint, create_geogrid_params
    from rift.biomass.geocode import geocode_biomass_granule, write_biomass_cog, read_available_polarizations

    granule = Path(granule)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if pols is None:
        pols = read_available_polarizations(granule)
        print(f"Detected available polarizations: {pols}")
    else:
        available = read_available_polarizations(granule)
        pols = [p for p in pols if p in available]
        if not pols:
            raise ValueError(f"None of the requested polarizations found in granule")
        missing = set(pols) - set(available)
        if missing:
            print(f"Warning: Requested polarizations {missing} not found, skipping")

    bbox = compute_biomass_footprint(granule, polarization_for_footprint)
    geogrid = create_geogrid_params(bbox, margin_m=margin, snap_to_master_grid=True, grid=grid)

    outputs = []
    base = granule.stem
    for pol in pols:
        complex_data, acq_time = geocode_biomass_granule(granule, dem, geogrid, pol)
        out = output_dir / f"{base}_{pol}_amp.tif"
        phase_out = None if amp_only else output_dir / f"{base}_{pol}_phs.tif"
        metadata = {
            "GRID_EPSG": str(geogrid["epsg"]),
            "POSTING": f"{geogrid['x_posting']}m × {geogrid['y_posting']}m",
            "POLARIZATION": pol,
            "ACQUISITION_TIME": acq_time.isoformat(),
            "BIOMASS_GRANULE": granule.name,
            "PROCESSING": "BIOMASS L1A SCS geocoded to master grid using isce3",
        }
        written = write_biomass_cog(out, complex_data, geogrid, acq_time, pol, metadata,
                                    phase_file=phase_out)
        outputs.extend(written)
    return outputs


def nisar_to_cogs(gslc: Path, output_dir: Path, *,
                  grid: AntarcticaGrid = ANTARCTICA_GRID,
                  pols: Optional[List[str]] = None,
                  amp_only: bool = False) -> List[Path]:
    """
    Extract freq-A amplitude (and phase) and place a NISAR GSLC onto COGs (per pol).

    Lossless placement onto the 5×5 m master grid (no resampling); raises if the granule
    origin does not align to the master-grid lattice.

    Args:
        gslc: Path to NISAR GSLC HDF5 file
        output_dir: Output directory for COG files
        grid: Target grid (default: ANTARCTICA_GRID, 5×5 m)
        pols: Polarizations to process (default: None = all available polarizations)
        amp_only: Write amplitude only (default: also write a separate phase COG per pol)

    Returns:
        List of paths to created COG files (amplitude and, unless amp_only, phase)
    """
    from rift.nisar.extract import extract_amplitude_to_cogs

    return extract_amplitude_to_cogs(
        Path(gslc), output_dir=Path(output_dir), polarizations=pols,
        grid=grid, amp_only=amp_only,
    )


def infer_cogs(cog_paths: List[Path], output_dir: Path, threshold: float) -> List[Path]:
    """Run the placeholder threshold model on each amplitude COG → binary-mask COGs."""
    from rift.infer.threshold import threshold_cog

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    masks = []
    for cog in cog_paths:
        cog = Path(cog)
        out = output_dir / f"{cog.stem}_mask.tif"
        threshold_cog(cog, out, threshold)
        masks.append(out)
    return masks


# --------------------------------------------------------------------------------------
# End-to-end workflows
# --------------------------------------------------------------------------------------

def _write_config(output_dir: Path, name: str, config: Dict) -> Path:
    """Write the resolved run config JSON alongside the outputs (self-describing job)."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{name}_config.json"
    with open(path, "w") as f:
        json.dump(config, f, indent=2, default=str)
    return path


def _finalize_intermediates(amp_cogs: List[Path], output_dir: Path,
                            keep_intermediates: bool) -> List[Path]:
    """Move amp COGs into output_dir if kept, else delete them. Returns kept paths."""
    output_dir = Path(output_dir)
    kept = []
    for cog in amp_cogs:
        cog = Path(cog)
        if keep_intermediates:
            dest = output_dir / cog.name
            if cog.resolve() != dest.resolve():
                shutil.move(str(cog), str(dest))
            kept.append(dest)
        else:
            if cog.exists():
                cog.unlink()
    return kept


def run_biomass_end_to_end(granule: Path, output_dir: Path, *,
                           dem: Optional[Path] = None,
                           x_spacing: float = 5.0, y_spacing: float = 5.0,
                           native: bool = False, margin: float = 5000.0,
                           threshold: float = 0.5, pols: Optional[List[str]] = None,
                           keep_intermediates: bool = False, amp_only: bool = False,
                           config: Optional[Dict] = None) -> Dict[str, List[Path]]:
    """
    BIOMASS end-to-end: ensure DEM → geocode → amplitude COGs → threshold → mask COGs.

    Masks always land in ``output_dir``. Amplitude (and phase) COGs land there only if
    ``keep_intermediates``; otherwise they are produced in a temp workdir and deleted.
    Inference always runs on the amplitude COGs only. Writes ``biomass_e2e_config.json``
    to ``output_dir``.

    Args:
        granule: Path to BIOMASS L1A SCS granule directory or .zip file
        output_dir: Output directory for final products
        dem: Path to DEM file (default: None = auto-download)
        x_spacing: Grid X spacing in meters (default: 5.0)
        y_spacing: Grid Y spacing in meters (default: 5.0)
        native: Use native BIOMASS posting (5×40 m) instead of requested spacing
        margin: Margin in meters around footprint (default: 5000.0)
        threshold: Threshold value for inference (default: 0.5)
        pols: Polarizations to process (default: None = all available)
        keep_intermediates: Keep amplitude/phase COGs in output_dir (default: False)
        amp_only: Write amplitude only (default: also write a separate phase COG per pol)
        config: Additional config metadata to include in output JSON

    Returns:
        dict: {"masks": [...], "amplitudes": [...], "config": path}
    """
    from rift.dem import ensure_dem
    from rift.biomass.geogrid import compute_biomass_footprint
    from rift.biomass.geocode import read_available_polarizations

    granule = Path(granule)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if pols is None:
        pols = read_available_polarizations(granule)
        print(f"Processing all available polarizations: {pols}")

    grid = _biomass_grid(x_spacing, y_spacing, native)

    resolved = {
        "workflow": "biomass-e2e", "granule": str(granule),
        "x_spacing": grid.x_posting, "y_spacing": grid.y_posting, "native": native,
        "margin": margin, "threshold": threshold, "pols": pols,
        "keep_intermediates": keep_intermediates, "amp_only": amp_only,
    }
    if config:
        resolved.update(config)

    # DEM: provided, else auto-download from the BIOMASS footprint.
    footprint = compute_biomass_footprint(granule, pols[0]) if dem is None else None
    dem_path = ensure_dem(dem, bbox=footprint, workdir=output_dir)
    resolved["dem"] = str(dem_path)

    workdir = Path(tempfile.mkdtemp(prefix="rift_biomass_", dir=output_dir))
    try:
        cogs = biomass_to_cogs(granule, dem_path, workdir, grid=grid, pols=pols,
                               margin=margin, polarization_for_footprint=pols[0],
                               amp_only=amp_only)
        # Inference runs on amplitude COGs only; phase is a passthrough product.
        amp_cogs = [c for c in cogs if c.name.endswith("_amp.tif")]
        masks = infer_cogs(amp_cogs, output_dir, threshold)
        kept = _finalize_intermediates(cogs, output_dir, keep_intermediates)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    cfg_path = _write_config(output_dir, "biomass_e2e", resolved)
    return {"masks": masks, "amplitudes": kept, "config": cfg_path}


def run_nisar_end_to_end(gslc: Path, output_dir: Path, *,
                         threshold: float = 0.5,
                         pols: Optional[List[str]] = None,
                         keep_intermediates: bool = False, amp_only: bool = False,
                         config: Optional[Dict] = None) -> Dict[str, List[Path]]:
    """
    NISAR end-to-end: extract+place → amplitude COGs → threshold → mask COGs.

    NISAR is placed losslessly onto the 5×5 m master grid (no resampling). Masks always
    land in ``output_dir``. Amplitude (and phase) COGs land there only if
    ``keep_intermediates``. Inference always runs on the amplitude COGs only. Writes
    ``nisar_e2e_config.json`` to ``output_dir``.

    Args:
        gslc: Path to NISAR GSLC HDF5 file
        output_dir: Output directory for final products
        threshold: Threshold value for inference (default: 0.5)
        pols: Polarizations to process (default: None = all available)
        keep_intermediates: Keep amplitude/phase COGs in output_dir (default: False)
        amp_only: Write amplitude only (default: also write a separate phase COG per pol)
        config: Additional config metadata to include in output JSON

    Returns:
        dict: {"masks": [...], "amplitudes": [...], "config": path}
    """
    from rift.nisar.extract import read_polarizations_list

    gslc = Path(gslc)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if pols is None:
        pols = read_polarizations_list(gslc)
        print(f"Processing all available polarizations: {pols}")

    grid = ANTARCTICA_GRID  # NISAR always uses the shared 5×5 m master grid.

    resolved = {
        "workflow": "nisar-e2e", "gslc": str(gslc),
        "x_spacing": grid.x_posting, "y_spacing": grid.y_posting,
        "threshold": threshold,
        "pols": pols, "keep_intermediates": keep_intermediates, "amp_only": amp_only,
    }
    if config:
        resolved.update(config)

    workdir = Path(tempfile.mkdtemp(prefix="rift_nisar_", dir=output_dir))
    try:
        cogs = nisar_to_cogs(gslc, workdir, grid=grid, pols=pols, amp_only=amp_only)
        # Inference runs on amplitude COGs only; phase is a passthrough product.
        amp_cogs = [c for c in cogs if c.name.endswith("_amp.tif")]
        masks = infer_cogs(amp_cogs, output_dir, threshold)
        kept = _finalize_intermediates(cogs, output_dir, keep_intermediates)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    cfg_path = _write_config(output_dir, "nisar_e2e", resolved)
    return {"masks": masks, "amplitudes": kept, "config": cfg_path}
