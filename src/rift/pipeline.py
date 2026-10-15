#!/usr/bin/env python3
"""
Per-granule orchestration for the two end-to-end workflows.

``rift`` exposes two independent end-to-end workflows — one for BIOMASS, one for NISAR.
They are **not** combined (there is no fusion step yet; that is a later phase). Each
workflow runs within a single MAAP DPS job: cross-granule fan-out, scheduling, and
retries are the platform's responsibility, not this module's.

Structure:
    * ``biomass_to_cogs`` / ``nisar_to_cogs`` — sensor COGs. The products written are
      selected by ``products`` (any of ``amp``, ``phs``, ``intensity``; default amp+phs).
    * ``infer_cogs`` — placeholder threshold → binary-mask COGs (runs on amplitude).
    * ``run_biomass_end_to_end`` / ``run_nisar_end_to_end`` — full chains that write the
      final products (and a resolved-config JSON) to ``output_dir``. Intermediate
      COGs are deleted by default (``keep_intermediates=False``) to minimize
      egress; pass ``keep_intermediates=True`` to keep them in ``output_dir``.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from rift.grid import ANTARCTICA_GRID, AntarcticaGrid


# --------------------------------------------------------------------------------------
# Product selection
# --------------------------------------------------------------------------------------

# The COG products the *2cog pipelines can emit, in canonical output order.
VALID_PRODUCTS = ("amp", "phs", "intensity")
# Default for the standalone *2cog workflows (amplitude + phase, mirroring the L1A layout).
DEFAULT_PRODUCTS = ("amp", "phs")


def _normalize_products(products: Optional[Sequence[str]]) -> List[str]:
    """Validate/normalize a ``products`` selection to a canonical, deduped list.

    Lowercases and strips each token, drops duplicates (preserving ``VALID_PRODUCTS``
    order), and raises ``ValueError`` on an empty selection or any unknown token so a
    typo (e.g. ``power``) fails loudly instead of silently writing nothing.
    """
    if products is None:
        products = DEFAULT_PRODUCTS
    seen = {str(p).strip().lower() for p in products}
    seen.discard("")
    if not seen:
        raise ValueError(
            f"No products selected; choose at least one of {list(VALID_PRODUCTS)}."
        )
    unknown = seen - set(VALID_PRODUCTS)
    if unknown:
        raise ValueError(
            f"Unknown product(s) {sorted(unknown)}; valid products are "
            f"{list(VALID_PRODUCTS)}."
        )
    return [p for p in VALID_PRODUCTS if p in seen]


def _require_product(products: Optional[Sequence[str]], required: str,
                     consumer: str) -> List[str]:
    """Normalize ``products`` and raise if ``required`` (the inference input) is absent.

    e2e workflows run inference on a specific product (``amp`` for the placeholder/NISAR
    crevasse path, ``intensity`` for the BIOMASS crevasse reader). If the user drops that
    product from the selection the run cannot proceed, so fail loudly up front.
    """
    normalized = _normalize_products(products)
    if required not in normalized:
        raise ValueError(
            f"{consumer} requires the {required!r} product, but products={normalized}. "
            f"Add {required!r} to --products."
        )
    return normalized


def _select_products(written: Sequence[Path], amp_path: Path,
                     products: Sequence[str]) -> List[Path]:
    """Post-process one polarization's written COGs to match the ``products`` selection.

    The low-level geocoders always write the amplitude COG (and the phase COG when a
    ``phase_file`` was requested). This derives the intensity COG from the amplitude when
    ``intensity`` is requested, drops the amplitude when ``amp`` was not requested, and
    returns the kept paths in canonical ``amp, phs, intensity`` order.
    """
    from rift.intensity import amp_to_intensity_cog

    amp_path = Path(amp_path)
    kept = {Path(p).name: Path(p) for p in written}  # amp (+ phs) from the geocoder

    if "intensity" in products:
        intensity = amp_to_intensity_cog(amp_path)
        kept[intensity.name] = intensity

    if "amp" not in products and amp_path.exists():
        amp_path.unlink()
        kept.pop(amp_path.name, None)

    order = {"amp": 0, "phs": 1, "intensity": 2}
    return sorted(kept.values(), key=lambda p: order.get(_product_of(p), 99))


def _product_of(path: Path) -> str:
    """Return the product token (amp/phs/intensity) implied by a COG filename suffix."""
    name = Path(path).name
    for token in VALID_PRODUCTS:
        if name.endswith(f"_{token}.tif"):
            return token
    return ""


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
                    products: Optional[Sequence[str]] = None) -> List[Path]:
    """
    Geocode a BIOMASS granule to per-polarization COGs (products chosen by ``products``).

    footprint → margin → snap-to-chunks geogrid → ISCE3 geocode_slc (complex) →
    |·| amplitude COG (+ ``angle`` phase COG and/or ``amp**2`` intensity COG per the
    selected ``products``).

    Args:
        granule: Path to BIOMASS L1A SCS granule directory or .zip file
        dem: Path to DEM file
        output_dir: Output directory for COG files
        grid: Target grid (default: ANTARCTICA_GRID)
        pols: Polarizations to process (default: None = all available polarizations)
        margin: Margin in meters to add around footprint (default: 5000.0)
        polarization_for_footprint: Polarization to use for footprint computation (default: "HH")
        products: COG products to write — any of ``amp``, ``phs``, ``intensity``
            (default: amp + phs). Intensity is derived from the amplitude COG.

    Returns:
        List of paths to created COG files (one per requested product per polarization)
    """
    from rift.biomass.geogrid import compute_biomass_footprint, create_geogrid_params
    from rift.biomass.geocode import geocode_biomass_to_cogs, read_available_polarizations

    products = _normalize_products(products)
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
        out = output_dir / f"{base}_{pol}_amp.tif"
        phase_out = (output_dir / f"{base}_{pol}_phs.tif") if "phs" in products else None
        metadata = {
            "GRID_EPSG": str(geogrid["epsg"]),
            "POSTING": f"{geogrid['x_posting']}m × {geogrid['y_posting']}m",
            "POLARIZATION": pol,
            "BIOMASS_GRANULE": granule.name,
            "PROCESSING": "BIOMASS L1A SCS geocoded to master grid using isce3",
        }
        # Block-wise geocode+write: bounds peak memory to the radar SLC + one output block
        # (never the full geocoded grid), so fine postings (e.g. 3 m) don't exhaust RAM.
        # The amplitude COG is always written here (it is the source for intensity); it is
        # removed below if ``amp`` was not requested.
        written = geocode_biomass_to_cogs(granule, dem, geogrid, pol, out, metadata,
                                          phase_file=phase_out)
        outputs.extend(_select_products(written, out, products))

    return outputs


def nisar_to_cogs(gslc: Path, output_dir: Path, *,
                  grid: AntarcticaGrid = ANTARCTICA_GRID,
                  pols: Optional[List[str]] = None,
                  products: Optional[Sequence[str]] = None) -> List[Path]:
    """
    Extract freq-A and place a NISAR GSLC onto COGs (per pol; products via ``products``).

    Lossless placement onto the 5×5 m master grid (no resampling); raises if the granule
    origin does not align to the master-grid lattice.

    Args:
        gslc: Path to NISAR GSLC HDF5 file
        output_dir: Output directory for COG files
        grid: Target grid (default: ANTARCTICA_GRID, 5×5 m)
        pols: Polarizations to process (default: None = all available polarizations)
        products: COG products to write — any of ``amp``, ``phs``, ``intensity``
            (default: amp + phs). Intensity is derived from the amplitude COG.

    Returns:
        List of paths to created COG files (one per requested product per polarization)
    """
    from rift.nisar.extract import extract_amplitude_to_cogs

    products = _normalize_products(products)
    # The extractor always writes amplitude (the intensity source); phase only when asked.
    written = extract_amplitude_to_cogs(
        Path(gslc), output_dir=Path(output_dir), polarizations=pols,
        grid=grid, amp_only=("phs" not in products),
    )

    outputs: List[Path] = []
    # Group the flat written list by polarization (keyed on the amp path) and post-process.
    amp_cogs = [Path(p) for p in written if Path(p).name.endswith("_amp.tif")]
    for amp in amp_cogs:
        base = amp.name[: -len("_amp.tif")]
        group = [Path(p) for p in written if Path(p).name.startswith(base + "_")]
        outputs.extend(_select_products(group, amp, products))
    return outputs


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
                           keep_intermediates: bool = False,
                           products: Optional[Sequence[str]] = None,
                           config: Optional[Dict] = None) -> Dict[str, List[Path]]:
    """
    BIOMASS end-to-end: ensure DEM → geocode → amplitude COGs → threshold → mask COGs.

    Masks always land in ``output_dir``. The selected ``products`` COGs land there only if
    ``keep_intermediates``; otherwise they are produced in a temp workdir and deleted.
    Inference runs on the amplitude COGs, so ``amp`` must be in ``products``. Writes
    ``biomass_e2e_config.json`` to ``output_dir``.

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
        keep_intermediates: Keep the product COGs in output_dir (default: False)
        products: COG products to write — any of ``amp``, ``phs``, ``intensity``
            (default: amp + phs). Must include ``amp`` (inference input).
        config: Additional config metadata to include in output JSON

    Returns:
        dict: {"masks": [...], "amplitudes": [...], "config": path}
    """
    from rift.dem import ensure_dem
    from rift.biomass.geogrid import compute_biomass_footprint
    from rift.biomass.geocode import read_available_polarizations

    products = _require_product(products, "amp", "biomass-e2e inference")
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
        "keep_intermediates": keep_intermediates, "products": products,
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
                               products=products)
        # Inference runs on amplitude COGs only; phase/intensity are passthrough products.
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
                         keep_intermediates: bool = False,
                         products: Optional[Sequence[str]] = None,
                         config: Optional[Dict] = None) -> Dict[str, List[Path]]:
    """
    NISAR end-to-end: extract+place → amplitude COGs → threshold → mask COGs.

    NISAR is placed losslessly onto the 5×5 m master grid (no resampling). Masks always
    land in ``output_dir``. The selected ``products`` COGs land there only if
    ``keep_intermediates``. Inference runs on the amplitude COGs, so ``amp`` must be in
    ``products``. Writes ``nisar_e2e_config.json`` to ``output_dir``.

    Args:
        gslc: Path to NISAR GSLC HDF5 file
        output_dir: Output directory for final products
        threshold: Threshold value for inference (default: 0.5)
        pols: Polarizations to process (default: None = all available)
        keep_intermediates: Keep the product COGs in output_dir (default: False)
        products: COG products to write — any of ``amp``, ``phs``, ``intensity``
            (default: amp + phs). Must include ``amp`` (inference input).
        config: Additional config metadata to include in output JSON

    Returns:
        dict: {"masks": [...], "amplitudes": [...], "config": path}
    """
    from rift.nisar.extract import read_polarizations_list

    products = _require_product(products, "amp", "nisar-e2e inference")
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
        "pols": pols, "keep_intermediates": keep_intermediates, "products": products,
    }
    if config:
        resolved.update(config)

    workdir = Path(tempfile.mkdtemp(prefix="rift_nisar_", dir=output_dir))
    try:
        cogs = nisar_to_cogs(gslc, workdir, grid=grid, pols=pols, products=products)
        # Inference runs on amplitude COGs only; phase/intensity are passthrough products.
        amp_cogs = [c for c in cogs if c.name.endswith("_amp.tif")]
        masks = infer_cogs(amp_cogs, output_dir, threshold)
        kept = _finalize_intermediates(cogs, output_dir, keep_intermediates)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    cfg_path = _write_config(output_dir, "nisar_e2e", resolved)
    return {"masks": masks, "amplitudes": kept, "config": cfg_path}
