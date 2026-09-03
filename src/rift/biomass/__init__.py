"""BIOMASS geocoding: footprint → chunk-aligned geogrid → ISCE3 geocode → amplitude COG."""

from rift.biomass.geogrid import compute_biomass_footprint, create_geogrid_params
from rift.biomass.geocode import (
    geocode_biomass_granule,
    geocode_biomass_to_cogs,
    write_biomass_cog,
    check_dem_covers_grid,
    DemCoverageError,
)

__all__ = [
    "compute_biomass_footprint",
    "create_geogrid_params",
    "geocode_biomass_granule",
    "geocode_biomass_to_cogs",
    "write_biomass_cog",
    "check_dem_covers_grid",
    "DemCoverageError",
]
