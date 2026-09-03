# Grid Spacing & Resampling — Design Decision

Status: **active default = 5×5 m**. This file records *why*, so the default can be
revisited later with the tradeoffs in front of us.

> **NISAR is placement-only (current implementation).** Because NISAR GSLCs already sit on
> the 5×5 m master lattice (see `BIOMASS_NISAR_Grid_Alignment_Proof.md`), the NISAR path
> does a *lossless windowed placement* onto the master grid at an integer pixel offset — no
> resampling, no interpolation, no subpixel shift. If a granule's origin is not on the
> lattice, the extractor raises rather than resampling. The spacing/anti-alias tradeoffs
> below are therefore **retained as design rationale** and still govern BIOMASS and any
> future decision to change the shared spacing; they are not options exposed on the NISAR
> path today. Choosing a non-5×5 NISAR grid would require reintroducing a resampling step.

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

### `--native` flag (BIOMASS only)

BIOMASS can opt out of the shared grid and use its natural **5×40 m** posting via
`--native`. In that mode cross-sensor chunk alignment is **not** guaranteed (different
spacing) — use only for single-sensor products or when downstream handles mixed grids.

NISAR has no `--native` (or spacing/resampling) option: its native posting **is** 5×5 m,
which is the shared grid, so it is always placed there losslessly.

## Two signal-processing rules (mandatory if any resampling is ever reintroduced)

These rules governed the original NISAR resample path. The current NISAR path does no
resampling (lossless placement only), so they do not apply to it today — but they remain
binding for BIOMASS complex handling and for any future decision to resample NISAR onto a
non-5×5 grid.

1. **Operate in the complex domain, then detect.** `|·|` roughly doubles signal
   bandwidth, so decimating the *detected* amplitude undersamples and aliases; and
   interpolating detected amplitude corrupts speckle statistics. Any resampling must act on
   the complex samples, taking magnitude **last**. Keeps both sensors' amplitude statistics
   consistent (BIOMASS is already complex-geocoded by ISCE3).

2. **Anti-alias before downsampling any axis.** Any axis whose spacing increases
   (e.g. a hypothetical NISAR 5→40 range) must be low-pass filtered (block-average /
   Lanczos) *before* decimation — nearest/bilinear alone will alias. A resampling-kernel
   choice must never bypass the anti-alias step on a downsampling path.

## Revisiting later

Spacing is parameterized, so changing the default is a config change, not a rewrite.
If NISAR detail preservation stops mattering, or storage/compactness dominates, 10×10
(balanced) or 5×40 (compact, BIOMASS-native) become attractive. Update this file and the
default in `grid.py` together.
