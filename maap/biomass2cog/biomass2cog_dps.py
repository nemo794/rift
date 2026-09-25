#!/usr/bin/env python3
"""DPS entrypoint for the rift ``biomass2cog`` OGC algorithm.

Resolves an ESA BIOMASS Level-1A SCS granule by STAC Item ID, downloads its full
product ``.zip`` on the worker using an ESA access token, then runs
``rift biomass2cog`` to geocode the range-doppler SLCs onto the Antarctica master
grid (EPSG:3031, 5x5 m, 512x512 chunks) via ISCE3 and write per-polarization
amplitude (and phase) COGs.

Unlike the NISAR path (ASF S3 + Earthdata), BIOMASS data lives on ESA's MAAP
infrastructure. Egress happens *inside* the algorithm (per MAAP guidance): we
exchange MAAP-managed ESA credentials for a short-lived access token and stream
the product zip over authenticated HTTPS with ``requests``. The auth/token flow
mirrors ``MAAP-Project/esa-biomass-gamma0``; the downloader does not (that
reference uses ``obstore`` against static assets — see the README for why the
on-the-fly ``/data/zipper/`` zip needs ``requests`` instead).

Credentials (``ESA_MAAP_CLIENT_SECRET`` / ``ESA_OFFLINE_TOKEN``) are read from
the environment first (local testing), then from MAAP secrets (on the worker).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import Optional, Tuple
from urllib.parse import urlsplit

ESA_STAC_API_URL = "https://catalog.maap.eo.esa.int/catalogue/"
ESA_TOKEN_URL = (
    "https://iam.maap.eo.esa.int/realms/esa-maap/protocol/openid-connect/token"
)
DEFAULT_COLLECTION = "BiomassLevel1a"
DEFAULT_POLS = "HH,HV,VH,VV"
# Full-product zip asset on the ESA MAAP STAC (served from the /data/zipper/ endpoint).
PRODUCT_ASSET_KEY = "product"


# --------------------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------------------
def _normalize_blank(value: Optional[str]) -> str:
    value = (value or "").strip()
    return "" if value in {"none", "None", "null", "NULL", '""', "''"} else value


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fetch an ESA BIOMASS L1A granule and run rift biomass2cog."
    )
    p.add_argument("--item_id", default="", help="BIOMASS L1A STAC Item ID.")
    p.add_argument("--collection", default=DEFAULT_COLLECTION)
    p.add_argument(
        "--pols",
        default=DEFAULT_POLS,
        help="Comma-separated polarizations (e.g. HH,HV,VH,VV).",
    )
    p.add_argument("--amp_only", default="false", help="true|false.")
    p.add_argument(
        "--out_dir",
        default=os.environ.get("USER_OUTPUT_DIR")
        or os.environ.get("OUTPUT_DIR")
        or "output",
    )
    args = p.parse_args()
    for attr in ("item_id", "collection", "pols", "out_dir"):
        setattr(args, attr, _normalize_blank(getattr(args, attr, "")))
    if not args.item_id:
        p.error("--item_id is required.")
    if not args.collection:
        args.collection = DEFAULT_COLLECTION
    if not args.pols:
        args.pols = DEFAULT_POLS
    return args


# --------------------------------------------------------------------------------------
# NASA Earthdata credentials setup (for the DEM download)
# --------------------------------------------------------------------------------------
EARTHDATA_HOST = "urs.earthdata.nasa.gov"


def _read_earthdata_secrets() -> Tuple[str, str]:
    """Return (username, password) for NASA Earthdata from env vars, else MAAP secrets.

    Mirrors ``_esa_secrets``: environment first (local testing), then the MAAP
    secrets store on the worker. Empty strings if neither source has them.
    """
    username = os.environ.get("EARTHDATA_USERNAME") or os.environ.get("EARTHDATA_LOGIN")
    password = os.environ.get("EARTHDATA_PASSWORD")
    if username and password:
        print("EARTHDATA_CREDS_SOURCE: environment", flush=True)
        return username, password

    try:
        from maap.maap import MAAP

        secrets = MAAP().secrets
        username = username or secrets.get_secret("EARTHDATA_USERNAME")
        password = password or secrets.get_secret("EARTHDATA_PASSWORD")
    except Exception as exc:  # noqa: BLE001
        print(f"EARTHDATA_CREDS: could not read MAAP secrets: {exc}", flush=True)
        return "", ""

    if username and password:
        print("EARTHDATA_CREDS_SOURCE: maap", flush=True)
    return username or "", password or ""


def _netrc_has_earthdata(netrc_path: str) -> bool:
    """True if ``netrc_path`` already has a complete entry for the Earthdata host."""
    import netrc

    try:
        auth = netrc.netrc(netrc_path).authenticators(EARTHDATA_HOST)
        return bool(auth and auth[0] and auth[2])  # login and password present
    except (OSError, netrc.NetrcParseError):
        return False


def _setup_earthdata_netrc() -> None:
    """
    Ensure ``~/.netrc`` has NASA Earthdata credentials for the sardem DEM download.

    The BIOMASS workflow geocodes against a DEM that ``sardem`` pulls from the NISAR
    DEM store (``nisar.asf.earthdatacloud.nasa.gov``), which sits behind NASA Earthdata
    Login — a NASA account entirely separate from the ESA credentials used to fetch the
    BIOMASS granule, and separate from ASF's temporary *S3* credentials (those are for
    granule download, not the DEM). sardem reads these credentials *only* from
    ``~/.netrc`` (it sets ``GDAL_HTTP_NETRC=YES`` and calls ``netrc.authenticators``);
    it does not consult ``EARTHDATA_*`` env vars, so we must materialize a .netrc here.

    DPS workers start clean (no ~/.netrc and no baked-in Earthdata identity — unlike ADE
    Hub workspaces), so the credentials must be registered once as MAAP secrets:
        MAAP().secrets.add_secret("EARTHDATA_USERNAME", "<username>")
        MAAP().secrets.add_secret("EARTHDATA_PASSWORD", "<password>")

    Idempotent: if a .netrc already has a valid Earthdata entry we leave it alone;
    otherwise we append one. Raises if no credentials can be found, so the job fails
    here with a clear message instead of deep inside sardem.
    """
    import stat

    netrc_path = os.path.expanduser("~/.netrc")
    if os.path.exists(netrc_path) and _netrc_has_earthdata(netrc_path):
        print(f"EARTHDATA_CREDS: existing .netrc entry for {EARTHDATA_HOST}", flush=True)
        return

    username, password = _read_earthdata_secrets()
    if not (username and password):
        raise RuntimeError(
            "NASA Earthdata credentials not found — the DEM download (sardem) needs "
            f"a NASA Earthdata account for {EARTHDATA_HOST}.\n"
            "DPS workers do not have these baked in; register them once as MAAP "
            "secrets from a MAAP Python session:\n"
            '    from maap.maap import MAAP\n'
            '    MAAP().secrets.add_secret("EARTHDATA_USERNAME", "<username>")\n'
            '    MAAP().secrets.add_secret("EARTHDATA_PASSWORD", "<password>")\n'
            "(or set EARTHDATA_USERNAME / EARTHDATA_PASSWORD env vars for local runs). "
            "Sign up free at https://urs.earthdata.nasa.gov/users/new"
        )

    entry = (
        f"machine {EARTHDATA_HOST}\n"
        f"    login {username}\n"
        f"    password {password}\n"
    )
    # Append (preserve any existing non-Earthdata machines); create if absent.
    mode = "a" if os.path.exists(netrc_path) else "w"
    with open(netrc_path, mode) as f:
        if mode == "a":
            f.write("\n")
        f.write(entry)
    os.chmod(netrc_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600 — netrc refuses looser perms
    print(f"EARTHDATA_CREDS: wrote {EARTHDATA_HOST} entry to {netrc_path}", flush=True)


# --------------------------------------------------------------------------------------
# ESA credentials + token exchange
# --------------------------------------------------------------------------------------
def _esa_secrets() -> Tuple[str, str]:
    """Return (client_secret, offline_token) from env vars, else MAAP secrets."""
    client_secret = os.environ.get("ESA_MAAP_CLIENT_SECRET")
    offline_token = os.environ.get("ESA_OFFLINE_TOKEN")
    if client_secret and offline_token:
        print("USING_ESA_CREDS_SOURCE: environment", flush=True)
        return client_secret, offline_token

    from maap.maap import MAAP

    secrets = MAAP().secrets
    client_secret = client_secret or secrets.get_secret("ESA_MAAP_CLIENT_SECRET")
    offline_token = offline_token or secrets.get_secret("ESA_OFFLINE_TOKEN")
    if not client_secret or not offline_token:
        raise RuntimeError(
            "Missing ESA credentials. Set ESA_MAAP_CLIENT_SECRET and "
            "ESA_OFFLINE_TOKEN as env vars or register them as MAAP secrets."
        )
    print("USING_ESA_CREDS_SOURCE: maap", flush=True)
    return client_secret, offline_token


def request_access_token(client_secret: str, offline_token: str) -> str:
    """Exchange the ESA offline token for a short-lived access token."""
    import requests

    resp = requests.post(
        ESA_TOKEN_URL,
        data={
            "client_id": os.environ.get("MAAP_CLIENT_ID", "offline-token"),
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": offline_token,
            "scope": "offline_access openid",
        },
        timeout=60,
    )
    resp.raise_for_status()
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError("ESA IAM response did not include an access token.")
    return token


# --------------------------------------------------------------------------------------
# STAC resolve + download
# --------------------------------------------------------------------------------------
def resolve_product_url(item_id: str, collection: str) -> str:
    """Return the full-product zip href for one BIOMASS L1A Item via the ESA STAC."""
    from pystac_client import Client

    print(f"SEARCHING STAC for {item_id} in {collection}", flush=True)
    item = next(
        Client.open(ESA_STAC_API_URL)
        .search(ids=[item_id], collections=[collection], limit=1)
        .items(),
        None,
    )
    if item is None:
        raise RuntimeError(
            f"No {collection} item found with id {item_id!r} on the ESA MAAP STAC."
        )
    asset = item.assets.get(PRODUCT_ASSET_KEY)
    if asset is None or not asset.href:
        raise RuntimeError(
            f"{item_id} is missing the {PRODUCT_ASSET_KEY!r} (zip) asset."
        )
    return asset.href


def download_product(item_id: str, url: str, token: str, dest_dir: str) -> str:
    """Stream the authenticated product zip to ``dest_dir/<item_id>.zip``.

    The full-product ``product`` asset is served from ESA's ``/data/zipper/``
    endpoint, which builds the zip on the fly and returns it with
    ``Transfer-Encoding: chunked`` and *no* ``Content-Length`` header. obstore's
    object-store HTTP backend rejects such responses (``MissingContentLength``),
    so we stream with ``requests`` instead, which handles chunked encoding
    transparently. See the README (`Downloader: requests vs obstore`) for why this
    differs from the ``esa-biomass-gamma0`` reference, which uses obstore against
    static, fixed-size enclosure assets.
    """
    import requests

    dest = os.path.join(dest_dir, f"{item_id}.zip")
    # Do not log the credentialed/ephemeral URL; log the host only.
    print(f"DOWNLOADING product zip from {urlsplit(url).netloc} -> {dest}", flush=True)
    with requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        stream=True,
        timeout=(60, 600),  # (connect, read) — read gaps, not total wall time
    ) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8 << 20):
                if chunk:
                    f.write(chunk)
    return dest


def fetch_granule(item_id: str, collection: str, input_dir: str) -> str:
    client_secret, offline_token = _esa_secrets()
    token = request_access_token(client_secret, offline_token)
    url = resolve_product_url(item_id, collection)
    return download_product(item_id, url, token, input_dir)


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

    # Setup NASA Earthdata credentials for DEM download (sardem requires these)
    _setup_earthdata_netrc()

    granule = fetch_granule(args.item_id, args.collection, input_dir)
    size_mb = os.path.getsize(granule) / (1 << 20)
    print(f"DOWNLOADED {granule} ({size_mb:.1f} MiB)", flush=True)

    # Grid is hardcoded to the shared 5x5 m master grid (CLI defaults); no --dem
    # (auto-downloaded via sardem from the granule footprint).
    cmd = [
        "rift",
        "biomass2cog",
        "--granule",
        granule,
        "--output",
        args.out_dir,
        "--pols",
        "[" + args.pols.strip() + "]",  # jsonargparse list syntax
    ]
    if str(args.amp_only).strip().lower() == "true":
        cmd += ["--amp-only"]

    print(f"RUNNING: {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    sys.exit(main())
