#!/usr/bin/env python3
"""OGC application-package entrypoint for the rift ``nisar2cog`` workflow.

Maps the OGC ``--<name> value`` inputs onto the ``rift nisar2cog`` CLI:

    run.py --gslc_url <url> [--pols HH,HV] [--amp_only true|false]

DPS convention: the granule is downloaded into ``./input`` and all products are written to
``./output`` (staged out by the platform via the CWL ``glob: ./output*``). Both directories
are created relative to the current working directory, which DPS sets to the job's scratch
directory.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

INPUT_DIR = Path("input")
OUTPUT_DIR = Path("output")
CHUNK = 1 << 20  # 1 MiB


def download(url: str, dest_dir: Path) -> Path:
    """Stream-download ``url`` into ``dest_dir`` using the URL's basename as the filename."""
    name = os.path.basename(urlparse(url).path) or "granule.h5"
    dest = dest_dir / name
    print(f"[run.py] downloading {url} -> {dest}", flush=True)
    with requests.get(url, stream=True, timeout=(30, 1800)) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=CHUNK):
                if chunk:
                    f.write(chunk)
    size_mb = dest.stat().st_size / (1 << 20)
    print(f"[run.py] downloaded {size_mb:.1f} MiB", flush=True)
    return dest


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OGC entrypoint: NISAR GSLC -> amplitude/phase COGs via rift nisar2cog."
    )
    parser.add_argument("--gslc_url", required=True,
                        help="HTTPS/S3 URL to a NISAR L2 GSLC .h5 granule.")
    parser.add_argument("--pols", default="",
                        help="Comma-separated pols (e.g. HH,HV). Empty = all freq-A pols.")
    parser.add_argument("--amp_only", default="false",
                        help="true|false. When true, write amplitude COGs only (no phase).")
    args = parser.parse_args()

    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    gslc = download(args.gslc_url, INPUT_DIR)

    cmd = ["rift", "nisar2cog", "--gslc", str(gslc), "--output", str(OUTPUT_DIR)]

    pols = args.pols.strip()
    if pols:
        # jsonargparse list syntax: --pols [HH,HV]
        cmd += ["--pols", "[" + pols + "]"]

    if str(args.amp_only).strip().lower() == "true":
        cmd += ["--amp-only"]

    print(f"[run.py] running: {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
