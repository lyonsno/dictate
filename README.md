# dictate

Global hold-to-dictate for macOS. Hold spacebar anywhere on the system — in your terminal, editor, browser, wherever — to record audio, transcribe it via a local Whisper server, and paste the result at your cursor.

Built with PyObjC. No Swift, no Xcode.

## How it works

```
Hold spacebar (400ms+) → Record audio → Transcribe on sidecar → Paste at cursor
```

A CGEventTap intercepts spacebar globally. Quick taps pass through as normal spaces. Holds trigger recording via `sounddevice`, send the audio to an OpenAI-compatible Whisper endpoint (e.g., `mlx-audio` on a sidecar machine), and inject the transcribed text via pasteboard + synthetic Cmd+V.

Runs as a menubar accessory app — mic icon in the menubar, no Dock icon.

## Architecture

```
dictate/
├── input_tap.py     # CGEventTap spacebar state machine (IDLE → WAITING → RECORDING)
├── capture.py       # sounddevice audio recording + RMS amplitude callback
├── transcribe.py    # httpx client for /v1/audio/transcriptions
├── inject.py        # pasteboard save → set text → Cmd+V → restore
├── menubar.py       # NSStatusItem with mic/mic.fill icons
└── __main__.py      # DictateAppDelegate — wires all layers together
```

Each layer is independent and testable in isolation.

## Requirements

- macOS 11+ (for SF Symbols and CGEventTap APIs)
- Python 3.13+
- [uv](https://docs.astral.sh/uv/)
- `portaudio` (for audio capture via sounddevice)
- A Whisper transcription server with an OpenAI-compatible `/v1/audio/transcriptions` endpoint

### System dependencies

```sh
brew install portaudio
```

### Whisper server

Any server that implements OpenAI's audio transcription API works. For local inference on Apple Silicon:

```sh
# On your sidecar machine (or locally):
uv tool install "mlx-audio[server]"
mlx-audio-server --host 0.0.0.0 --port 8000
```

## Usage

```sh
# Clone and install
git clone https://github.com/lyonsno/dictate.git
cd dictate
uv sync

# Run (point at your Whisper server)
DICTATE_WHISPER_URL=http://<sidecar-ip>:8000 uv run dictate
```

On first run, macOS will prompt for Accessibility permission. Grant it to your terminal app (Terminal.app, iTerm2, Ghostty, etc.) in System Settings → Privacy & Security → Accessibility.

### Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `DICTATE_WHISPER_URL` | Yes | — | Whisper server base URL |
| `DICTATE_WHISPER_MODEL` | No | `mlx-community/whisper-large-v3-turbo` | Model identifier |
| `DICTATE_HOLD_MS` | No | `400` | Hold threshold in milliseconds |

## Tests

```sh
uv run pytest -v
```

45 tests covering the state machine, WAV encoding, HTTP client, injection, and menubar — all run headless with mocked PyObjC.

## Roadmap

### Phase 1 — Core dictation ✅

Global hold-to-dictate: spacebar hold detection, audio capture, Whisper transcription, paste at cursor. Menubar accessory with mic icon. 45 tests, all headless.

### Phase 2 — Visual feedback

**Menubar amplitude animation.** The menubar icon becomes a live visualizer while recording — a glowing bar that oscillates with voice amplitude, inspired by Claude Code's hold-to-dictate cursor. The RMS amplitude callback in `capture.py` already fires per-chunk; this phase connects it to a visual.

- [ ] Animated NSStatusItem that responds to amplitude in real time
- [ ] Smooth interpolation between amplitude samples (avoid jitter)
- [ ] Idle/recording state transitions with visual continuity

**Frosted transcription overlay.** A semi-transparent, system-font overlay appears on screen showing the transcription as it's produced. When recording ends and text is pasted at the cursor, the overlay fades out — the fade distracts from the paste so it feels seamless rather than jarring.

- [ ] Borderless `NSWindow` overlay with frosted/vibrancy background
- [ ] System font text rendering (SF Pro, matched to system appearance)
- [ ] Smooth fade-out animation timed to coincide with paste injection
- [ ] Overlay centered horizontally, fixed near bottom of screen (not cursor-tracking)
- [ ] Dark mode / light mode support via system appearance

### Phase 3 — Streaming transcription

**Incremental transcription during recording.** Instead of waiting for the recording to finish before transcribing, send audio buffer snapshots to the Whisper server while still recording. The overlay shows interim (partial) results that refine as more audio arrives, so you see your words appearing in near-real-time.

- [ ] Periodic `get_buffer()` snapshots sent during recording (infrastructure already in `capture.py`)
- [ ] Interim vs. final transcription state in the overlay (partial results shown in lighter weight or opacity)
- [ ] Debounce/interval tuning to balance responsiveness vs. server load
- [ ] Graceful degradation if the server can't keep up (fall back to final-only)

### Phase 4 — Polish

- [ ] LaunchAgent for auto-start at login
- [ ] Config file (`~/.config/dictate/config.json`) — hold threshold, server URL, model, overlay preferences
- [ ] Configurable hotkey (alternatives to spacebar hold)

## License

MIT
