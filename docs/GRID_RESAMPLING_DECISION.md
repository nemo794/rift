# Grid Spacing & Resampling — Design Decision

Status: **active default = 5×5 m**. This file records *why*, so the default can be
revisited later with the tradeoffs in front of us.

## Context

All products land on a single **master grid** in EPSG:3031 (Antarctic Polar
Stereographic) with 512×512-pixel COG chunks (see [GRID_SYSTEM.md](GRID_SYSTEM.md)).
The grid's pixel spacing is a **parameter** (`x_spacing`, `y_spacing`), not a constant.

Two sensors feed the grid, with different native sampling:

| Sensor  | Band       | Native resolution (az × rg) | Native GSLC posting | Character   |
|---------|------------|-----------------------------|---------------------|-------------|
| BIOMASS | P (~70 cm) | ~6.5 m × ~46 m              | —                   | anisotropic, range-coarse |
| NISAR   | L (~24 cm) | few m (≈isotropic)          | 5 m × 5 m           | isotropic, fine |

**Key distinction:** *posting (pixel spacing) ≠ resolution.* Resolution is fixed at
acquisition by bandwidth (range) and synthetic aperture (azimuth). Resampling changes
the sampling lattice, not the information content. Upsampling recovers no detail;
downsampling with a proper anti-alias filter discards detail deliberately. No grid
choice makes the two sensors physically equal in resolution — the grid choice is about
**posting/chunk ergonomics and speckle statistics**, not equalizing sharpness.

## Cross-sensor chunk alignment requires *same origin AND same spacing*

For a 512×512 chunk to cover the same ground for both sensors (needed for the ML step),
both the **origin lattice** and the **spacing** must match. Same origin but different
spacing → chunk (i,j) covers different ground per sensor. Therefore, when cross-sensor
alignment is desired, **both sensors resample onto one shared grid.**

## Options considered

| Grid    | NISAR fidelity        | BIOMASS fidelity        | Pixel shape | Speckle effect          | Volume   | ML ergonomics |
|---------|-----------------------|-------------------------|-------------|-------------------------|----------|---------------|
| 5×40    | range detail lost (asymmetric) | native ✓        | anisotropic | NISAR multilooked ✓     | small    | anisotropic kernels |
| **5×5** | **native ✓ (best)**   | range upsampled 8× (redundant) | isotropic | BIOMASS lightly over-smoothed | large | best (symmetric, sharp) |
| 10×10   | slight symmetric loss | range upsampled 4×      | isotropic   | both lightly multilooked | moderate | good, balanced |

- **5×40** keeps BIOMASS native and multilooks NISAR (genuine speckle benefit), but
  guts NISAR range resolution in one axis only → anisotropic *resolution*.
- **5×5** keeps NISAR native and isotropic; BIOMASS range is upsampled 8× (redundant,
  correlated samples, no new information) — but nothing is *destroyed*.
- **10×10** is the balanced compromise: isotropic, mild symmetric treatment of both,
  moderate volume; neither sensor at native.

## Decision

**Default: 5×5 m** for the shared master grid.

- Rationale: preserve NISAR's full L-band resolution, keep pixels isotropic (symmetric
  conv kernels, cleanest for CNN-style ML), guarantee cross-sensor chunk co-registration
  by default. Cost is redundant BIOMASS range upsampling and larger volume — acceptable.
- BIOMASS reaches 5×5 for free: ISCE3 geocodes the **complex** SLC directly onto the
  target grid (correct by construction), so the "upsampling" is just a fine geocode.

### `--native` flag

Opt out of the shared grid and use each sensor's natural posting:

- BIOMASS → **5×40 m**
- NISAR   → **5×5 m**

In `--native` mode, cross-sensor chunk alignment is **not** guaranteed (different
spacing). Use only for single-sensor products or when downstream handles mixed grids.

## Two signal-processing rules (mandatory, independent of grid choice)

1. **Resample NISAR in the complex domain, then detect.** `|·|` roughly doubles signal
   bandwidth, so decimating the *detected* amplitude undersamples and aliases; and
   interpolating detected amplitude corrupts speckle statistics. Resample the geocoded
   complex GSLC, then take magnitude **last**. Keeps both sensors' amplitude statistics
   consistent (BIOMASS is already complex-geocoded by ISCE3).

2. **Anti-alias before downsampling any axis.** Any axis whose spacing increases
   (e.g. NISAR 5→40 range) must be low-pass filtered (block-average / Lanczos) *before*
   decimation. Nearest/bilinear alone will alias. The resampling-method parameter selects
   the kernel but must not bypass the anti-alias step on downsampling paths.

## Revisiting later

Spacing is parameterized, so changing the default is a config change, not a rewrite.
If NISAR detail preservation stops mattering, or storage/compactness dominates, 10×10
(balanced) or 5×40 (compact, BIOMASS-native) become attractive. Update this file and the
default in `grid.py` together.
