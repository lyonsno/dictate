# Perceptasia Throughglass Provider Contract

`Perceptasia Throughglass Graft` is a Spoke-owned stack/window consumer of the
House optical primitive. Perceptasia is the provider of spatial content, not
the owner of the Spoke window lifecycle or optical animation contract.

The current provider is provisional:

- viewer URL: `SPOKE_PERCEPTASIA_THROUGHGLASS_URL`, default
  `http://localhost:8742`
- scene URL: `SPOKE_PERCEPTASIA_THROUGHGLASS_SCENE_URL`, default
  `${viewer_url}/scene.json`
- selection file: `SPOKE_PERCEPTASIA_SELECTION_PATH`, default
  `~/.local/state/perceptasia/selection.json`

The stable ask to Perceptasia is a small embed manifest endpoint, not a
commitment to the current development server shape:

```json
{
  "schema": "perceptasia.embed-manifest.v0",
  "viewer_url": "http://localhost:8742/",
  "scene_url": "http://localhost:8742/scene.json",
  "selection": {
    "schema": "perceptasia.selection.v1",
    "path": "~/.local/state/perceptasia/selection.json"
  },
  "capabilities": {
    "reload": true,
    "selection_publish": true,
    "spoke_stack_embed": true
  }
}
```

Spoke may use the localhost viewer while this manifest is absent, but Spoke
should not harden around accidental Perceptasia dev-server details. The
Throughglass window is the integration boundary: Spoke owns showing, hiding,
placement, optical-field requests, and eventual stack membership; Perceptasia
owns scene generation, spatial interaction semantics, and selection payloads.
