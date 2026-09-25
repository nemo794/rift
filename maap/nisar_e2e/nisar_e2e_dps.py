#!/usr/bin/env python3
"""DPS entrypoint for the rift ``nisar-e2e`` OGC algorithm.

End-to-end NISAR crevasse detection, chaining two conda envs behind one entrypoint:

  1. **geocode** (env ``rift_nisar2cog``): resolve + download a NISAR L2 GSLC granule and
     run ``rift nisar2cog`` to produce per-polarization amplitude (and phase) COGs. Granule
     access mirrors MAAP's ``nisar_access_subset`` reference (S3 temp creds / CMR / auth
     HTTPS) — identical to the ``nisar2cog`` package.
  2. **inference** (env ``crevasse``): run ``crevasse-export-geotiff nisar`` on the HH
     amplitude COG to write ``gate_prob.tif`` + ``unet_prob.tif`` into the same ``output/``.

This script runs *inside* the ``rift_nisar2cog`` env (see run.sh); it shells out to the
``crevasse`` env for step 2 via ``conda run -n crevasse``.
"""

from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys
from typing import List, Optional, Tuple

DEFAULT_ASF_S3_CREDS_URL = "https://nisar.asf.earthdatacloud.nasa.gov/s3credentials"


# --------------------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------------------
def _normalize_blank(value: Optional[str]) -> str:
    value = (value or "").strip()
    return "" if value in {"none", "None", "null", "NULL", '""', "''"} else value


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fetch a NISAR GSLC granule, run rift nisar2cog, then crevasse inference."
    )
    p.add_argument("--access_mode", choices=["auto", "s3", "https"], default="auto")
    p.add_argument("--s3_href", default="")
    p.add_argument("--https_href", default="")
    p.add_argument("--short_name", default="NISAR_L2_GSLC_PROVISIONAL_V1")
    p.add_argument("--granule_index", type=int, default=0)
    p.add_argument("--count", type=int, default=50)
    p.add_argument("--asf_s3_creds_url", default=DEFAULT_ASF_S3_CREDS_URL)
    p.add_argument("--pols", default="")
    p.add_argument("--amp_only", default="false")
    p.add_argument("--max_tiles", default="",
                   help="Cap on candidate tiles for inference (prefix of scan order). "
                        "Empty = full swath.")
    p.add_argument("--crop_to_scanned", default="false",
                   help="true|false. Crop inference GeoTIFFs to the scanned bounding box.")
    p.add_argument("--bedmap_mask", default="",
                   help="Bedmap3 grounded-ice mask for the pre-scoring candidate filter. "
                        "'true' (or 'default') uses the crevasse-bundled mask; a path uses "
                        "your own; empty (default) disables grounded filtering. Requires "
                        "min_grounded.")
    p.add_argument("--min_grounded", default="",
                   help="Drop candidate tiles whose Bedmap3 grounded-ice fraction is below "
                        "this (e.g. 0.80) before any gate/U-Net scoring. Empty (default) = "
                        "off. Requires bedmap_mask.")
    p.add_argument(
        "--out_dir",
        default=os.environ.get("USER_OUTPUT_DIR") or os.environ.get("OUTPUT_DIR") or "output",
    )
    args = p.parse_args()
    for attr in ("s3_href", "https_href", "pols", "max_tiles", "out_dir"):
        setattr(args, attr, _normalize_blank(getattr(args, attr, "")))
    return args


# --------------------------------------------------------------------------------------
# Earthdata / CMR helpers
# --------------------------------------------------------------------------------------
def _login_earthaccess():
    import earthaccess

    if os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD"):
        return earthaccess.login(strategy="environment")
    netrc_path = os.environ.get("NETRC") or os.path.expanduser("~/.netrc")
    if os.path.exists(netrc_path):
        return earthaccess.login()
    # On MAAP the credential machinery may still allow S3 creds without EDL login;
    # only HTTPS strictly requires this.
    return earthaccess.login(strategy="environment")


def _first_h5(links: List[str]) -> str:
    return next((u for u in (links or []) if u.lower().endswith(".h5")),
                (links[0] if links else ""))


def resolve_hrefs(args: argparse.Namespace) -> Tuple[str, str]:
    """Return (https_href, s3_href), resolving via CMR search when neither is supplied."""
    if args.https_href or args.s3_href:
        return args.https_href, args.s3_href

    import earthaccess

    _login_earthaccess()
    results = earthaccess.search_data(
        short_name=args.short_name, count=args.count, cloud_hosted=True
    )
    if not results:
        raise RuntimeError(
            f"No granules found for short_name={args.short_name}. "
            "Provide --s3_href or --https_href explicitly."
        )
    if args.granule_index >= len(results):
        raise IndexError(
            f"--granule_index {args.granule_index} out of range for {len(results)} result(s)."
        )
    g = results[args.granule_index]
    return _first_h5(g.data_links()), _first_h5(g.data_links(access="direct"))


# --------------------------------------------------------------------------------------
# Download
# --------------------------------------------------------------------------------------
def _s3_credentials(asf_s3_creds_url: str) -> dict:
    key = os.environ.get("AWS_ACCESS_KEY_ID")
    secret = os.environ.get("AWS_SECRET_ACCESS_KEY")
    token = os.environ.get("AWS_SESSION_TOKEN")
    if key and secret and token:
        print("USING_S3_CREDS_SOURCE: environment", flush=True)
        return {"accessKeyId": key, "secretAccessKey": secret, "sessionToken": token}

    from maap.maap import MAAP

    creds = MAAP().aws.earthdata_s3_credentials(asf_s3_creds_url)
    print("USING_S3_CREDS_SOURCE: maap", flush=True)
    return creds


def _download_s3(s3_href: str, asf_s3_creds_url: str, dest_dir: str) -> str:
    if not s3_href:
        raise RuntimeError("S3 href not available.")
    import s3fs

    creds = _s3_credentials(asf_s3_creds_url)
    fs = s3fs.S3FileSystem(
        anon=False,
        key=creds["accessKeyId"],
        secret=creds["secretAccessKey"],
        token=creds["sessionToken"],
    )
    dest = os.path.join(dest_dir, os.path.basename(s3_href))
    print(f"OPENING_SOURCE_MODE: s3 -> {dest}", flush=True)
    fs.get(s3_href, dest)
    return dest


def _download_https(https_href: str, dest_dir: str) -> str:
    if not https_href:
        raise RuntimeError("HTTPS href not available.")
    auth = _login_earthaccess()
    session = auth.get_session()
    dest = os.path.join(dest_dir, os.path.basename(https_href))
    print(f"OPENING_SOURCE_MODE: https -> {dest}", flush=True)
    with session.get(https_href, stream=True, allow_redirects=True, timeout=(30, 1800)) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=8 * 1024 * 1024):
                if chunk:
                    f.write(chunk)
    return dest


def fetch_granule(args: argparse.Namespace, input_dir: str) -> str:
    https_href, s3_href = resolve_hrefs(args)
    print(f"RESOLVED https={https_href!r} s3={s3_href!r}", flush=True)

    if args.access_mode == "https":
        return _download_https(https_href, input_dir)
    if args.access_mode == "s3":
        return _download_s3(s3_href, args.asf_s3_creds_url, input_dir)

    # auto: S3 first, HTTPS fallback.
    if s3_href:
        try:
            return _download_s3(s3_href, args.asf_s3_creds_url, input_dir)
        except Exception as exc:  # noqa: BLE001
            print(f"S3_DOWNLOAD_FAILED: {exc}", flush=True)
    if https_href:
        return _download_https(https_href, input_dir)
    raise RuntimeError("Could not download granule (no usable s3_href/https_href).")


# --------------------------------------------------------------------------------------
# Steps
# --------------------------------------------------------------------------------------
def run_nisar2cog(gslc: str, out_dir: str, pols: str, amp_only: str) -> int:
    """Step 1: geocode to amplitude (and phase) COGs, in this (rift_nisar2cog) env."""
    cmd = ["rift", "nisar2cog", "--gslc", gslc, "--output", out_dir]
    pols = pols.strip()
    if pols:
        cmd += ["--pols", "[" + pols + "]"]           # jsonargparse list syntax
    if str(amp_only).strip().lower() == "true":
        cmd += ["--amp-only"]
    print(f"RUNNING: {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd).returncode


def _find_hh_amp(out_dir: str) -> str:
    """Locate the HH amplitude COG rift nisar2cog just wrote (``*_HH_amp.tif``).

    The crevasse NISAR path expects a single-band frequency-A HH amplitude raster; fall
    back to any ``*_amp.tif`` if no HH pol exists in this granule."""
    hh = sorted(glob.glob(os.path.join(out_dir, "*_HH_amp.tif")))
    if hh:
        return hh[0]
    any_amp = sorted(glob.glob(os.path.join(out_dir, "*_amp.tif")))
    if any_amp:
        print(f"WARNING: no *_HH_amp.tif; using {os.path.basename(any_amp[0])}", flush=True)
        return any_amp[0]
    raise RuntimeError(f"No amplitude COG (*_amp.tif) found in {out_dir} for inference.")


def run_crevasse(amp_cog: str, out_dir: str, max_tiles: str, crop_to_scanned: str,
                 bedmap_mask: str, min_grounded: str) -> int:
    """Step 2: crevasse gate + U-Net inference, in the `crevasse` env.

    Writes gate_prob.tif + unet_prob.tif into out_dir alongside the amplitude COGs."""
    inner = ["crevasse-export-geotiff", "nisar",
             "--granule", amp_cog, "--out-dir", out_dir]
    max_tiles = (max_tiles or "").strip()
    if max_tiles:
        inner += ["--max-tiles", max_tiles]
    if str(crop_to_scanned).strip().lower() == "true":
        inner += ["--crop-to-scanned"]

    # Grounded-ice pre-filter (crevasse.common.grounded_filter). The two crevasse flags
    # are required together; keep that contract here rather than sending a half-pair.
    mask = (bedmap_mask or "").strip()
    grounded = (min_grounded or "").strip()
    if bool(mask) != bool(grounded):
        print("WARNING: bedmap_mask and min_grounded must be given together; "
              "ignoring the grounded-ice filter for this run.", flush=True)
    elif mask and grounded:
        # 'true'/'default' -> the crevasse-bundled mask (flag passed with no value);
        # anything else is treated as a path to a mask GeoTIFF.
        if mask.lower() in {"true", "default"}:
            inner += ["--bedmap-mask"]
        else:
            inner += ["--bedmap-mask", mask]
        inner += ["--min-grounded", grounded]

    cmd = ["conda", "run", "--live-stream", "-n", "crevasse"] + inner
    print(f"RUNNING: {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd).returncode


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------
def main() -> int:
    args = parse_args()
    os.makedirs(args.out_dir, exist_ok=True)
    # DPS convention: stage the granule into ./input (a real dir under the job workdir,
    # not /tmp, so it shares the job's disk budget and mirrors the DPS layout).
    input_dir = os.path.abspath("input")
    os.makedirs(input_dir, exist_ok=True)

    gslc = fetch_granule(args, input_dir)
    size_mb = os.path.getsize(gslc) / (1 << 20)
    print(f"DOWNLOADED {gslc} ({size_mb:.1f} MiB)", flush=True)

    rc = run_nisar2cog(gslc, args.out_dir, args.pols, args.amp_only)
    if rc != 0:
        print(f"nisar2cog failed (rc={rc}); skipping inference.", flush=True)
        return rc

    amp_cog = _find_hh_amp(args.out_dir)
    print(f"INFERENCE_INPUT: {amp_cog}", flush=True)
    return run_crevasse(amp_cog, args.out_dir, args.max_tiles, args.crop_to_scanned,
                        args.bedmap_mask, args.min_grounded)


if __name__ == "__main__":
    sys.exit(main())
