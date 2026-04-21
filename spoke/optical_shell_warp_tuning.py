"""Shared optical-shell warp tuning constants.

The CI and Metal renderers are supposed to implement the same capsule warp.
Keep their cross-renderer tuning in one module so the two paths cannot drift
silently.
"""

WARP_BLEED_ZONE_FRAC = 0.8
WARP_CENTER_FLOOR = 0.80
WARP_FIELD_EXPONENT = 0.35
WARP_REMAP_BASE_EXP_SCALE = 0.98
WARP_REMAP_BASE_EXP_FLOOR = 0.02
WARP_REMAP_RIM_EXP = 0.1
WARP_CURVEBOOST_CAP = 0.95
WARP_CURVEBOOST_MAG_SCALE = 0.35
WARP_CURVEBOOST_RING_DIVISOR = 240.0
WARP_CURVEBOOST_RING_CAP = 0.55
WARP_SPINE_PROXIMITY_BOOST = 1.5
WARP_X_SQUEEZE = 2.5
WARP_Y_SQUEEZE = 1.5
WARP_EXTERIOR_MAG_STRENGTH = 0.6
WARP_EXTERIOR_MAG_DECAY = 2.0
