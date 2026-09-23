# Slim image for the rift nisar2cog OGC workflow.
#
# nisar2cog uses only numpy/scipy/h5py/rasterio/pyproj/jsonargparse (GDAL is bundled in the
# rasterio wheel), so no isce3 / conda is required -- this sidesteps the isce3 0.25.17 /
# gdal 3.13.3 conda solve issues tracked in NASA-IMPACT/science-support#81.
FROM python:3.12-slim

# libexpat1 is needed by rasterio's bundled GDAL and is omitted from python:3.12-slim.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

# The build context is the repo root (the GitHub Action checks out the whole repo).
COPY . /opt/rift

# Install rift (pulls its runtime deps from pyproject.toml) plus requests for run.py.
RUN pip install --no-cache-dir /opt/rift requests

# OGC entrypoint on PATH; run_command in algorithm_config.yml is "run.py".
COPY maap/nisar2cog/run.py /usr/local/bin/run.py
RUN chmod +x /usr/local/bin/run.py
