#!/usr/bin/env python3
"""DPS entrypoint for the rift ``nisar2cog`` OGC algorithm.

Resolves a NISAR L2 GSLC granule and downloads it on the worker, then runs
``rift nisar2cog`` to produce per-polarization amplitude (and phase) COGs.

Granule access mirrors MAAP's ``nisar_access_subset`` reference:
  * ``s3`` (preferred): pull ``s3://sds-n-cumulus-prod-nisar-products/...`` with ASF
    temporary S3 credentials from ``maap.aws.earthdata_s3_credentials`` (or injected
    ``AWS_*`` env vars).
  * ``https`` (fallback): authenticated Earthdata HTTPS via ``earthaccess`` (env creds
    or ``~/.netrc``).
  * ``auto``: try S3 first, then HTTPS.

If neither ``--s3_href`` nor ``--https_href`` is supplied, the granule is resolved by a
CMR search on ``--short_name`` / ``--granule_index``.
"""

from __future__ import annotations

import argparse
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
        description="Fetch a NISAR GSLC granule and run rift nisar2cog."
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
    p.add_argument(
        "--out_dir",
        default=os.environ.get("USER_OUTPUT_DIR") or os.environ.get("OUTPUT_DIR") or "output",
    )
    args = p.parse_args()
    for attr in ("s3_href", "https_href", "pols", "out_dir"):
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

    cmd = ["rift", "nisar2cog", "--gslc", gslc, "--output", args.out_dir]
    pols = args.pols.strip()
    if pols:
        cmd += ["--pols", "[" + pols + "]"]           # jsonargparse list syntax
    if str(args.amp_only).strip().lower() == "true":
        cmd += ["--amp-only"]

    print(f"RUNNING: {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    sys.exit(main())
