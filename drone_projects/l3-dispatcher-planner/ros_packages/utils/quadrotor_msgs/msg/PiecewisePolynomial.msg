# Canonical optimized-trajectory representation for the ground-station
# trajectory channel (ground-station-channels.spec.md §2.5). Every planner
# backend (ego/super/diff) repackages its own optimizer coefficients into
# this message via launch-side remaps to the canonical topic
# /drone_<id>/planner/optimized_traj — no format conversion, no
# backend-specific station code.

Header header

# Number of polynomial pieces (segments).
uint32 n_seg
# Polynomial order K (degree); each axis carries K + 1 coefficients.
uint8 order

# Segment durations [s], one per segment.
float64[] durations

# Coefficients, row-major array of length n_seg * 3 * (order + 1):
# segment-major, then per-axis x/y/z blocks. Within segment i
# (base = i * 3 * (order + 1)):
#   cx = coeffs[base + 0*(order+1) : base + (order+1)]
#   cy = coeffs[base + 1*(order+1) : base + 2*(order+1)]
#   cz = coeffs[base + 2*(order+1) : base + 3*(order+1)]
# Each axis block is ascending power: index j is the coefficient of t^j.
float64[] coeffs
