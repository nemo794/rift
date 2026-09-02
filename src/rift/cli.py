#!/usr/bin/env python3
"""
Unified ``rift`` command-line interface (jsonargparse).

Subcommands
-----------
End-to-end (single MAAP job per granule; writes mask COGs + a resolved-config JSON):
    biomass-e2e   BIOMASS granule → amplitude COGs → binary-mask COGs
    nisar-e2e     NISAR GSLC     → amplitude COGs → binary-mask COGs

Individual steps (for local development / debugging):
    biomass2cog   BIOMASS granule → amplitude COGs
    nisar2cog     NISAR GSLC     → amplitude COGs
    biomass-infer amplitude COG  → binary-mask COG (threshold placeholder)
    nisar-infer   amplitude COG  → binary-mask COG (threshold placeholder)
    validate      Check geogrid JSON alignment to the master grid

Grid spacing defaults to 5×5 m (shared BIOMASS/NISAR grid). ``--native`` uses per-sensor
native posting (BIOMASS 5×40, NISAR 5×5); in native mode cross-sensor chunk alignment is
not guaranteed. ``--keep-intermediates`` (e2e only, default off) keeps amplitude/phase COGs
in the output directory instead of deleting them.

COG products default to a per-polarization amplitude COG (``_<pol>_amp.tif``) plus a
co-registered phase COG (``_<pol>_phs.tif``, radians -π..π), mirroring the source L1A
abs/phase measurement layout. ``--amp-only`` writes amplitude only. Inference always runs
on the amplitude COG.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional

from jsonargparse import ArgumentParser


def _build_parser() -> ArgumentParser:
    parser = ArgumentParser(prog="rift", description="BIOMASS/NISAR → master grid → inference")
    sub = parser.add_subcommands(dest="subcommand", required=True)

    # --- biomass-e2e ------------------------------------------------------------------
    p = ArgumentParser(description="BIOMASS end-to-end: granule → amplitude COGs → mask COGs")
    p.add_argument("--granule", type=Path, required=True, help="BIOMASS L1A SCS granule (dir or .zip)")
    p.add_argument("--output", type=Path, required=True, help="Output directory")
    p.add_argument("--dem", type=Path, help="DEM (EPSG:3031 or 4326); auto-downloaded if omitted")
    p.add_argument("--x-spacing", type=float, default=5.0)
    p.add_argument("--y-spacing", type=float, default=5.0)
    p.add_argument("--native", action="store_true", help="BIOMASS-native 5×40 spacing")
    p.add_argument("--margin", type=float, default=5000.0, help="Footprint margin (m)")
    p.add_argument("--threshold", type=float, default=0.5, help="Inference amplitude threshold")
    p.add_argument("--pols", type=List[str], default=["HH"], help="Polarizations, e.g. [HH,HV]")
    p.add_argument("--keep-intermediates", action="store_true",
                   help="Keep amplitude/phase COGs in output/ (default: delete)")
    p.add_argument("--amp-only", action="store_true",
                   help="Write amplitude only (default: also write a separate phase COG per pol)")
    sub.add_subcommand("biomass-e2e", p)

    # --- nisar-e2e --------------------------------------------------------------------
    p = ArgumentParser(description="NISAR end-to-end: GSLC → amplitude COGs → mask COGs")
    p.add_argument("--gslc", type=Path, required=True, help="NISAR L2 GSLC HDF5 file")
    p.add_argument("--output", type=Path, required=True, help="Output directory")
    p.add_argument("--x-spacing", type=float, default=5.0)
    p.add_argument("--y-spacing", type=float, default=5.0)
    p.add_argument("--native", action="store_true", help="Keep NISAR-native 5×5 (snap only)")
    p.add_argument("--resampling", type=str, default="nearest",
                   choices=["nearest", "bilinear", "lanczos", "average"])
    p.add_argument("--no-antialias", action="store_true",
                   help="Disable anti-alias low-pass before downsampling (risky)")
    p.add_argument("--threshold", type=float, default=0.5)
    p.add_argument("--pols", type=Optional[List[str]], default=None,
                   help="Polarizations (default: all freq-A)")
    p.add_argument("--keep-intermediates", action="store_true")
    p.add_argument("--amp-only", action="store_true",
                   help="Write amplitude only (default: also write a separate phase COG per pol)")
    sub.add_subcommand("nisar-e2e", p)

    # --- biomass2cog ------------------------------------------------------------------
    p = ArgumentParser(description="BIOMASS granule → amplitude COGs (no inference)")
    p.add_argument("--granule", type=Path, required=True)
    p.add_argument("--dem", type=Path, help="DEM; auto-downloaded if omitted")
    p.add_argument("--output", type=Path, required=True, help="Output directory")
    p.add_argument("--x-spacing", type=float, default=5.0)
    p.add_argument("--y-spacing", type=float, default=5.0)
    p.add_argument("--native", action="store_true")
    p.add_argument("--margin", type=float, default=5000.0)
    p.add_argument("--pols", type=List[str], default=["HH"])
    p.add_argument("--amp-only", action="store_true",
                   help="Write amplitude only (default: also write a separate phase COG per pol)")
    sub.add_subcommand("biomass2cog", p)

    # --- nisar2cog --------------------------------------------------------------------
    p = ArgumentParser(description="NISAR GSLC → amplitude COGs (no inference)")
    p.add_argument("--gslc", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True, help="Output directory")
    p.add_argument("--x-spacing", type=float, default=5.0)
    p.add_argument("--y-spacing", type=float, default=5.0)
    p.add_argument("--native", action="store_true")
    p.add_argument("--resampling", type=str, default="nearest",
                   choices=["nearest", "bilinear", "lanczos", "average"])
    p.add_argument("--no-antialias", action="store_true")
    p.add_argument("--pols", type=Optional[List[str]], default=None)
    p.add_argument("--amp-only", action="store_true",
                   help="Write amplitude only (default: also write a separate phase COG per pol)")
    sub.add_subcommand("nisar2cog", p)

    # --- biomass-infer / nisar-infer --------------------------------------------------
    for name, desc in [("biomass-infer", "BIOMASS amplitude COG → binary-mask COG"),
                       ("nisar-infer", "NISAR amplitude COG → binary-mask COG")]:
        p = ArgumentParser(description=desc)
        p.add_argument("--input", type=Path, required=True, help="Input amplitude COG")
        p.add_argument("--output", type=Path, required=True, help="Output mask COG")
        p.add_argument("--threshold", type=float, required=True)
        sub.add_subcommand(name, p)

    # --- validate ---------------------------------------------------------------------
    p = ArgumentParser(description="Validate geogrid JSON alignment to the master grid")
    p.add_argument("--geogrids", type=List[Path], required=True, help="Geogrid JSON file(s)")
    sub.add_subcommand("validate", p)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    from rift.biomass.geocode import DemCoverageError
    try:
        return _dispatch(argv)
    except DemCoverageError as e:
        print(f"\nERROR: {e}", file=sys.stderr)
        return 1


def _dispatch(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    cfg = parser.parse_args(argv if argv is not None else sys.argv[1:])
    cmd = cfg.subcommand
    args = getattr(cfg, cmd)

    if cmd == "biomass-e2e":
        from rift.pipeline import run_biomass_end_to_end
        result = run_biomass_end_to_end(
            args.granule, args.output, dem=args.dem,
            x_spacing=args.x_spacing, y_spacing=args.y_spacing, native=args.native,
            margin=args.margin, threshold=args.threshold, pols=args.pols,
            keep_intermediates=args.keep_intermediates, amp_only=args.amp_only,
        )
        _report(result)

    elif cmd == "nisar-e2e":
        from rift.pipeline import run_nisar_end_to_end
        result = run_nisar_end_to_end(
            args.gslc, args.output,
            x_spacing=args.x_spacing, y_spacing=args.y_spacing, native=args.native,
            method=args.resampling, antialias=not args.no_antialias,
            threshold=args.threshold, pols=args.pols,
            keep_intermediates=args.keep_intermediates, amp_only=args.amp_only,
        )
        _report(result)

    elif cmd == "biomass2cog":
        from rift.pipeline import biomass_to_cogs, _biomass_grid
        from rift.dem import ensure_dem
        from rift.biomass.geogrid import compute_biomass_footprint
        grid = _biomass_grid(args.x_spacing, args.y_spacing, args.native)
        footprint = compute_biomass_footprint(args.granule, args.pols[0]) if args.dem is None else None
        dem_path = ensure_dem(args.dem, bbox=footprint, workdir=args.output)
        outs = biomass_to_cogs(args.granule, dem_path, args.output, grid=grid,
                               pols=args.pols, margin=args.margin,
                               polarization_for_footprint=args.pols[0],
                               amp_only=args.amp_only)
        _report_list(outs)

    elif cmd == "nisar2cog":
        from rift.pipeline import nisar_to_cogs, _nisar_grid
        grid = _nisar_grid(args.x_spacing, args.y_spacing)
        outs = nisar_to_cogs(args.gslc, args.output, grid=grid, pols=args.pols,
                             native=args.native, method=args.resampling,
                             antialias=not args.no_antialias, amp_only=args.amp_only)
        _report_list(outs)

    elif cmd in ("biomass-infer", "nisar-infer"):
        from rift.infer.threshold import threshold_cog
        out = threshold_cog(args.input, args.output, args.threshold)
        print(f"✓ Wrote mask COG: {out}")

    elif cmd == "validate":
        from rift.validate import validate_multiple_geogrids
        ok = validate_multiple_geogrids(args.geogrids)
        return 0 if ok else 1

    return 0


def _report(result: dict) -> None:
    print(f"\n✓ Config: {result['config']}")
    print(f"✓ Masks ({len(result['masks'])}):")
    for m in result["masks"]:
        print(f"    {m}")
    if result.get("amplitudes"):
        print(f"✓ Amplitude COGs kept ({len(result['amplitudes'])}):")
        for a in result["amplitudes"]:
            print(f"    {a}")


def _report_list(outs: list) -> None:
    print(f"\n✓ Created {len(outs)} COG(s):")
    for o in outs:
        print(f"    {o}")


if __name__ == "__main__":
    sys.exit(main())
