# Review Authority Surfaces

This document extends Topothesia beyond public-doc routing and into review
authority. Use it when a reviewer, agent, or maintenance pass needs to know
which implementation path is canonical, which path is fallback-only, and when
surface drift should be treated as design pressure rather than material breakage.

When the human says `Make this durable for review`, choose the narrowest durable
control that fits the situation:

- Update `docs/review_surfaces.toml` and this document when the issue is about
  authority, canonical-vs-fallback interpretation, allowed divergence, or other
  review-routing semantics.
- Update the repo-local Prilosec registry when the issue is a recurring
  acknowledged false positive or accepted finding family that future reviews
  should suppress or demote.
- Update only the review artifact when the issue is specific to one reviewed
  commit and does not need a standing repo-level rule.

Topothesia review surfaces are for authority and routing, not generic
suppression.

## Optical Shell Renderer Authority

For optical-shell warp tuning, [`spoke/metal_warp.py`](../spoke/metal_warp.py)
is the authoritative implementation surface.

[`spoke/backdrop_stream.py`](../spoke/backdrop_stream.py) remains a fallback
and compatibility surface. The two paths may diverge during tuning without
that drift automatically counting as a material regression.

Default review posture: treat bare constant drift or comment/code mismatch
between these two paths as design pressure, not as a must-fix bug.

The Metal shell's deep interior is intentionally a flat max-mip interior, not
a magnifying lens over live screen detail. The visual goal is for material to
spread around the optical shell and settle into a flattened body. Do not treat
the deep interior ignoring `mip_blur_strength` as a bug by itself; that knob is
allowed to shape the transition/scar band while the center remains flat.

Visible transition discontinuities at the edge of the flat interior are still
valid review pressure. A square-looking mip boundary, hard cutoff, or obvious
coarse-mip cell pattern should be reviewed as a transition-smoothing problem,
not as a reason to reintroduce crisp sampling in the interior.

Promote the finding to material only if one of these becomes true:

- an executable contract explicitly requires equivalence
- the authoritative Metal path regresses observable behavior
- the project later re-declares the CI/backdrop path a co-equal production
  renderer instead of a fallback surface

Revisit this authority declaration when the optical-shell tuning family reaches
katastasis or when the fallback renderer becomes product-authoritative in its
own right.
