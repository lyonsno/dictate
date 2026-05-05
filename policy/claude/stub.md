<!-- Sources: policy/shared/core.md — read it first, this file adds Claude Code deltas only -->

## Building the .app bundle

For .app distribution testing (not normal dev smoke testing):

```sh
pkill -TERM -f "Spoke" 2>/dev/null
sleep 1
rm -f ~/Library/Logs/.spoke.lock
./scripts/build.sh --fast
rm -rf ~/Applications/Spoke.app
cp -r dist/Spoke.app ~/Applications/
open ~/Applications/Spoke.app
```

For full clean builds (after dependency changes, spec file changes, or when
`--fast` builds behave unexpectedly):

```sh
./scripts/build.sh
```

## Permissions

- **Ad-hoc signed .app bundles cannot reliably get Accessibility on Sequoia.** System Settings shows the toggle as on but silently drops the grant — it never writes to the TCC database. This is a Sequoia limitation, not a bug in Spoke.
- **Workaround for development**: Run via `uv run spoke` from Terminal. Terminal.app has a real Apple signature with a working Accessibility grant, and the Python process inherits it.
- **Permanent fix**: Sign with a Developer ID certificate ($99/yr Apple Developer Program). This is also required for distribution (notarization, no Gatekeeper warnings).
- Every rebuild changes the ad-hoc signature, which may invalidate macOS TCC permissions (Accessibility, Microphone).
- If permissions stop working after a rebuild, the TCC daemon has cached a stale CDHash. Fix: `sudo tccutil reset Accessibility com.noahlyons.spoke`, re-grant in System Settings, and **reboot**.
- Do NOT run `tccutil reset` in build scripts.
- Do NOT change the bundle identifier to work around TCC.
- Use `pkill -TERM` (not `-9`) to kill the app so the SIGTERM handler can cleanly uninstall the CGEventTap.
- After rebuilding and relaunching, **ask the user if the spacebar is working** before doing anything else.
