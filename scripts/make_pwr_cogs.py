#!/usr/bin/env python3
"""Create per-polarization intensity (a.k.a. power) COGs from geocoded amplitude COGs.

Thin command-line wrapper around :func:`rift.intensity.make_intensity_cogs`. The
intensity logic now lives in the ``rift`` package (so the pipelines can emit intensity
COGs in-process via ``--products``); this script is kept for ad-hoc / standalone use
against a directory of ``*_<POL>_amp.tif`` COGs.

Usage::

    python scripts/make_pwr_cogs.py <data_dir> [--output-dir DIR]

By default the intensity COGs are written to the same directory as their source amplitude
COGs. Existing intensity COGs are always overwritten.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make ``rift`` importable when run from a source checkout without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rift.intensity import make_intensity_cogs  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "data_dir",
        type=Path,
        help="Directory containing *_<POL>_amp.tif COGs",
    )
    ap.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory for the intensity COGs (default: same as each input)",
    )
    args = ap.parse_args()

    data_dir = args.data_dir.resolve()
    if not data_dir.is_dir():
        print(f"ERROR: not a directory: {data_dir}", file=sys.stderr)
        return 1

    written = make_intensity_cogs(data_dir, output_dir=args.output_dir)
    if not written:
        print("No amplitude COGs found.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
