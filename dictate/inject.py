"""Text injection via pasteboard + synthetic Cmd+V.

Saves the current pasteboard contents, sets the transcribed text,
sends a synthetic Cmd+V keystroke, then restores the original
pasteboard after a short delay.
"""

from __future__ import annotations

import logging
import time

from AppKit import NSPasteboard, NSPasteboardTypeString
from Foundation import NSTimer
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    CGEventSetFlags,
    kCGEventFlagMaskCommand,
    kCGHIDEventTap,
)

logger = logging.getLogger(__name__)

_V_KEYCODE = 9
_RESTORE_DELAY_S = 0.15  # seconds before restoring pasteboard


def inject_text(text: str) -> None:
    """Paste *text* at the current cursor position.

    1. Save current pasteboard string
    2. Set pasteboard to *text*
    3. Synthesize Cmd+V
    4. Schedule pasteboard restore after a short delay
    """
    if not text:
        return

    pb = NSPasteboard.generalPasteboard()

    # Save whatever string is on the pasteboard (best-effort)
    saved_string = pb.stringForType_(NSPasteboardTypeString)

    # Set our text
    pb.clearContents()
    pb.setString_forType_(text, NSPasteboardTypeString)

    # Synthesize Cmd+V
    _post_cmd_v()

    logger.info("Injected %d chars", len(text))

    # Restore pasteboard after a delay (must run on main thread via NSTimer)
    def _restore_pasteboard(timer: NSTimer) -> None:
        pb.clearContents()
        if saved_string:
            pb.setString_forType_(saved_string, NSPasteboardTypeString)
        logger.debug("Pasteboard restored")

    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        _RESTORE_DELAY_S,
        _PasteboardRestorer.alloc().initWithCallback_(_restore_pasteboard),
        "fire:",
        None,
        False,
    )


def _post_cmd_v() -> None:
    """Post a synthetic Cmd+V keystroke."""
    src = None  # default event source

    down = CGEventCreateKeyboardEvent(src, _V_KEYCODE, True)
    CGEventSetFlags(down, kCGEventFlagMaskCommand)

    up = CGEventCreateKeyboardEvent(src, _V_KEYCODE, False)
    CGEventSetFlags(up, kCGEventFlagMaskCommand)

    CGEventPost(kCGHIDEventTap, down)
    CGEventPost(kCGHIDEventTap, up)


# ── tiny helper to bridge NSTimer → Python callable ──────────

import objc as _objc  # noqa: E402
from Foundation import NSObject  # noqa: E402


class _PasteboardRestorer(NSObject):
    """NSObject wrapper so NSTimer can call back into Python."""

    def initWithCallback_(self, callback):
        self = _objc.super(_PasteboardRestorer, self).init()
        if self is None:
            return None
        self._callback = callback
        return self

    def fire_(self, timer):
        self._callback(timer)
