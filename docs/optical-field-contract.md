# Optical Field Primitive Contract

This is the consumer-facing contract for shared optical-shell UI surfaces.
Consumers describe what they want; the primitive/backend owns how the field
materializes, resizes, rests, dismisses, and cleans itself up.

## Consumer Shape

Use `spoke.optical_field.OpticalFieldRequest` as the adapter boundary:

```python
from spoke.optical_field import (
    OpticalFieldBounds,
    OpticalFieldProfileRef,
    OpticalFieldRequest,
)

request = OpticalFieldRequest(
    caller_id="agent.card.codex-1",
    bounds=OpticalFieldBounds(x=40, y=80, width=320, height=96),
    role="agent_card",
    profile=OpticalFieldProfileRef(base="agent_card"),
).as_materializing()
```

Required consumer-owned data:

- `caller_id`: stable namespaced visual id, such as `agent.card.<session-id>`.
- `bounds`: desired compositor-space rectangle.
- `role`: coarse caller role for ordering and diagnostics.
- `profile`: named material language plus bounded profile/slot overrides.
- `disturbances`: optional data-only transient or persistent field requests.

Primitive-owned behavior:

- lifecycle progress, timing, and cleanup
- shader constants and field composition
- old-to-new resize interpolation
- SDF/mask/fill continuity
- interruption and cleanup of stranded summon/dismiss/resize state

## Lifecycle Helpers

Prefer the helpers over hand-written state strings:

```python
request = request.as_materializing()
request = request.as_resting()
request = request.resize_to(OpticalFieldBounds(x=60, y=80, width=420, height=120))
request = request.as_dismissing()
request = request.as_hidden()
```

`resize_to(...)` preserves `previous_bounds` in the request and compiled
metadata. That is the handoff the primitive uses to own resize continuity.
Consumers should not animate resize locally or call warp/fill phases directly.

The current preview-smooth backend still exposes `progress` in compiled metadata
because the live pressure-slit compositor consumes it during materialize and
dismiss. Consumers should treat that as backend-owned animation state unless a
specific adapter is explicitly acting as the lifecycle clock.

## Profiles And Slots

Profiles are named visual languages. Current bases are available from
`available_optical_field_profiles()` and include:

- `assistant_shell`
- `preview_pill`
- `agent_card`
- `quiet_chip`

Per-slot overrides are allowed as data:

```python
from spoke.optical_field import OpticalFieldSlotOverride

profile = OpticalFieldProfileRef(
    base="agent_card",
    slots={
        "resize": OpticalFieldSlotOverride(
            params={"ring_amplitude_frac": 0.08}
        ),
    },
)
```

Slots map to primitive lifecycle phases: `rest`, `materialize`, `dismiss`, and
`resize`. `hidden` compiles no visible shell config.

Dismiss seam orientation is contract data, not consumer shader plumbing. If a
consumer needs a different split direction, use the dismiss slot rather than
forking compositor keys:

```python
profile = OpticalFieldProfileRef(
    base="agent_card",
    slots={
        "dismiss": OpticalFieldSlotOverride(
            params={"dismiss_seam_axis_rotation": 1.0}
        ),
    },
)
```

The backend translates these profile params into the current Metal shader keys
(`scar_seam_length_frac`, `scar_seam_thickness_frac`,
`scar_seam_focus_frac`, `scar_axis_rotation`, and related grip controls).
Consumers should not emit those shader keys directly.

## Do Not

- Do not fork shader parameters into consumer code.
- Do not hand-drive materialization, dismiss, or resize progress unless the adapter explicitly owns the lifecycle clock.
- Do not compensate locally for stranded displacement, missing fill, wrong scale, resize slow-motion, or summon/dismiss residue.
- Do not treat `AgentShellPrimitive.material` as already equal to this API; use an adapter that maps rendered surfaces to `OpticalFieldRequest`.

If a consumer sees stranded warp, missing fill, wrong scale, resize slow-motion,
or summon/dismiss residue, file it against the House primitive/packet rather
than patching around it downstream.

## Placeholder Backend

`OpticalFieldPlaceholderBackend` is intentionally a compatibility bridge. It
keeps the request API stable while compiling into today's shell-config
dictionaries. Consumers may use it for tests and early adapters, but should keep
their code shaped around `OpticalFieldRequest`, not around the compiled config.
