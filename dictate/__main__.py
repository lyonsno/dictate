"""Entry point for dictate — macOS global hold-to-dictate.

Run with:  uv run dictate
    or:    uv run python -m dictate

Configure via environment variables:
    DICTATE_WHISPER_URL    Sidecar Whisper server URL (required)
    DICTATE_WHISPER_MODEL  Model name (default: mlx-community/whisper-large-v3-turbo)
    DICTATE_HOLD_MS        Hold threshold in ms (default: 400, must be > 0)
    DICTATE_RESTORE_DELAY_MS  Pasteboard restore delay in ms (default: 1000)
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time

import objc
from AppKit import (
    NSAlert,
    NSApp,
    NSApplication,
    NSApplicationActivationPolicyAccessory,
)
from Foundation import NSObject

from .capture import AudioCapture
from .glow import GlowOverlay
from .inject import inject_text
from .input_tap import SpacebarHoldDetector
from .menubar import MenuBarIcon
from .transcribe import TranscriptionClient

logger = logging.getLogger(__name__)


class DictateAppDelegate(NSObject):
    """Main application delegate — wires input → capture → transcribe → inject."""

    def init(self):
        self = objc.super(DictateAppDelegate, self).init()
        if self is None:
            return None

        whisper_url = os.environ.get("DICTATE_WHISPER_URL", "")
        if not whisper_url:
            logger.error("DICTATE_WHISPER_URL is required")
            print(
                "ERROR: Set DICTATE_WHISPER_URL to your sidecar Whisper server URL.\n"
                "  Example: DICTATE_WHISPER_URL=http://192.168.68.125:8000 uv run dictate",
                file=sys.stderr,
            )
            sys.exit(1)

        model = os.environ.get(
            "DICTATE_WHISPER_MODEL", "mlx-community/whisper-large-v3-turbo"
        )
        hold_ms_raw = os.environ.get("DICTATE_HOLD_MS", "400")
        try:
            hold_ms = int(hold_ms_raw)
        except ValueError:
            logger.error("DICTATE_HOLD_MS must be an integer, got %r", hold_ms_raw)
            print(
                f"ERROR: DICTATE_HOLD_MS must be an integer, got {hold_ms_raw!r}.\n"
                "  Example: DICTATE_HOLD_MS=400 uv run dictate",
                file=sys.stderr,
            )
            sys.exit(1)

        if hold_ms <= 0:
            logger.error("DICTATE_HOLD_MS must be > 0, got %d", hold_ms)
            print(
                f"ERROR: DICTATE_HOLD_MS must be > 0, got {hold_ms}.\n"
                "  Example: DICTATE_HOLD_MS=400 uv run dictate",
                file=sys.stderr,
            )
            sys.exit(1)

        self._capture = AudioCapture()
        self._client = TranscriptionClient(base_url=whisper_url, model=model)
        self._detector = SpacebarHoldDetector.alloc().initWithHoldStart_holdEnd_holdMs_(
            self._on_hold_start,
            self._on_hold_end,
            hold_ms,
        )
        self._menubar: MenuBarIcon | None = None
        self._glow: GlowOverlay | None = None
        self._transcribing = False
        self._transcription_token = 0
        return self

    # ── NSApplication delegate ──────────────────────────────

    def applicationDidFinishLaunching_(self, notification) -> None:
        self._menubar = MenuBarIcon.alloc().initWithQuitCallback_(self._quit)
        self._menubar.setup()

        self._glow = GlowOverlay.alloc().initWithScreen_(None)
        self._glow.setup()

        if not self._detector.install():
            self._show_accessibility_alert()
            self._quit()
            return

        logger.info("dictate ready — hold spacebar to record")
        self._menubar.set_status_text("Ready — hold spacebar")

    # ── hold callbacks (called on main thread) ──────────────

    def _on_hold_start(self) -> None:
        logger.info("Hold started — recording")
        if self._menubar is not None:
            self._menubar.set_recording(True)
            self._menubar.set_status_text("Recording…")
        if self._glow is not None:
            self._glow.show()
        self._capture.start(amplitude_callback=self._on_amplitude)

    def _on_amplitude(self, rms: float) -> None:
        """Called from PortAudio thread — marshal to main thread.

        PyObjC's performSelectorOnMainThread requires an ObjC-bridgeable
        object, so we wrap the float in a NSNumber-compatible wrapper.
        """
        from Foundation import NSNumber
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "amplitudeUpdate:", NSNumber.numberWithFloat_(rms), False
        )

    def amplitudeUpdate_(self, rms_number) -> None:
        """Main thread: forward amplitude to glow overlay."""
        if self._glow is not None:
            self._glow.update_amplitude(float(rms_number))

    def _on_hold_end(self) -> None:
        logger.info("Hold ended — transcribing")
        wav_bytes = self._capture.stop()

        if self._glow is not None:
            self._glow.hide()
        if self._menubar is not None:
            self._menubar.set_recording(False)
            self._menubar.set_status_text("Transcribing…")

        if not wav_bytes:
            logger.warning("No audio captured")
            if self._menubar is not None:
                self._menubar.set_status_text("Ready — hold spacebar")
            return

        # Invalidate any in-flight transcription so its result is discarded
        self._transcription_token += 1
        token = self._transcription_token

        self._transcribing = True
        self._transcribe_start = time.monotonic()
        thread = threading.Thread(
            target=self._transcribe_worker, args=(wav_bytes, token), daemon=True
        )
        thread.start()

    def _transcribe_worker(self, wav_bytes: bytes, token: int) -> None:
        """Background thread: send audio to Whisper, marshal result to main thread."""
        try:
            text = self._client.transcribe(wav_bytes)
        except Exception:
            logger.exception("Transcription failed")
            self.performSelectorOnMainThread_withObject_waitUntilDone_(
                "transcriptionFailed:", {"token": token}, False
            )
            return

        elapsed_ms = (time.monotonic() - self._transcribe_start) * 1000
        self.performSelectorOnMainThread_withObject_waitUntilDone_(
            "transcriptionComplete:",
            {"token": token, "text": text, "elapsed_ms": elapsed_ms},
            False,
        )

    def transcriptionComplete_(self, payload: dict) -> None:
        """Main thread: inject transcribed text at cursor."""
        if payload["token"] != self._transcription_token:
            logger.info("Discarding stale transcription (token %d)", payload["token"])
            return
        self._transcribing = False
        text = payload["text"]
        if text:
            def _on_clipboard_restored():
                if self._menubar is not None:
                    self._menubar.set_status_text("Ready — hold spacebar")

            inject_text(text, on_restored=_on_clipboard_restored)
            elapsed_ms = payload.get("elapsed_ms", 0)
            logger.info("Injected: %r (%.0fms)", text, elapsed_ms)
            if self._menubar is not None:
                self._menubar.set_status_text("Pasted!")
            return
        if self._menubar is not None:
            self._menubar.set_status_text("Ready — hold spacebar")

    def transcriptionFailed_(self, payload: dict) -> None:
        """Main thread: handle transcription error."""
        if payload["token"] != self._transcription_token:
            return  # stale failure, ignore
        self._transcribing = False
        logger.error("Transcription failed — no text injected")
        if self._menubar is not None:
            self._menubar.set_status_text("Error — try again")

    # ── helpers ─────────────────────────────────────────────

    def _quit(self) -> None:
        self._detector.uninstall()
        self._client.close()
        NSApp.terminate_(None)

    def _show_accessibility_alert(self) -> None:
        """Show a dialog explaining the Accessibility permission requirement."""
        alert = NSAlert.new()
        alert.setMessageText_("Accessibility Permission Required")
        alert.setInformativeText_(
            "dictate needs Accessibility access to detect spacebar holds.\n\n"
            "Go to System Settings → Privacy & Security → Accessibility "
            "and enable access for your terminal app (Terminal, iTerm2, etc.).\n\n"
            "Then relaunch dictate."
        )
        alert.addButtonWithTitle_("OK")
        # Temporarily become a regular app so the alert is visible
        NSApp.setActivationPolicy_(1)  # NSApplicationActivationPolicyRegular
        alert.runModal()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    delegate = DictateAppDelegate.alloc().init()
    app.setDelegate_(delegate)

    from PyObjCTools import AppHelper

    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
