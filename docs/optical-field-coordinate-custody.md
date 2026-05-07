# Optical Field Coordinate Custody

`OpticalFieldRequest` geometry enters House with explicit coordinate custody. The renderer normalizes accepted geometry to display-local points before compiling the legacy shell config, and records the source coordinate space in `optical_field` metadata when the request crosses a non-default boundary.

Supported coordinate spaces:

- `display_points`: display-local logical points, already normalized for compositor use.
- `screen_points`: global screen points; requires `display_origin`.
- `backing_pixels`: backing pixel coordinates; requires `backing_scale`.
- `parent_points`: points local to a parent surface; requires `parent_origin`.
- `content_points`: points local to a content frame; requires `content_origin`.

Requests may carry `display_id`, `display_epoch`, and `source_epoch`. `OpticalFieldPlaceholderBackend` can be seeded with current display and source epochs; stale request epochs are rejected before geometry is stored or compiled.

Optical bounds and content frames are separate. `bounds` describes the optical envelope House animates and shades. `content_frame` describes where text, cards, labels, or debug payloads may be placed. When they differ, both are normalized independently and recorded in metadata so tests can prove the old point/pixel/parent-local ambiguity is gone.
