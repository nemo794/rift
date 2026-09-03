"""
rift

Geocode ESA BIOMASS and reproject NISAR GSLC granules to a master grid over
Antarctica, extract amplitude Cloud-Optimized GeoTIFFs, and run inference.
"""

__version__ = "0.1.0"

from rift.grid import AntarcticaGrid, ANTARCTICA_GRID

__all__ = ["AntarcticaGrid", "ANTARCTICA_GRID", "__version__"]
