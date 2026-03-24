"""Screen-border glow overlay that pulses with voice amplitude.

A borderless, transparent, click-through NSWindow that draws a soft glow
around the screen edges. Intensity follows the RMS amplitude of the
microphone input, with fast rise and slow decay for a breathing effect.
"""

from __future__ import annotations

import logging

import objc
from AppKit import (
    NSBezierPath,
    NSColor,
    NSScreen,
    NSView,
    NSWindow,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorStationary,
)
from Foundation import NSObject
from Quartz import (
    CAGradientLayer,
    CALayer,
    CAShapeLayer,
    CGPathCreateWithRoundedRect,
    kCAFillRuleEvenOdd,
)

logger = logging.getLogger(__name__)

# Glow appearance
_GLOW_COLOR = (0.7, 0.92, 0.95)  # pale turquoise-white blue RGB
_GLOW_WIDTH = 10.0  # thinner source — less intrusion into screen
_GLOW_SHADOW_RADIUS = 30.0  # tighter bloom — stays near the edge
_GLOW_MAX_OPACITY = 1.0  # full brightness at peak to compensate for smaller size
_GLOW_BASE_OPACITY = 0.05  # barely-there base in silence
_CORNER_RADIUS = 10.0  # macOS screen corner radius

# Amplitude smoothing: rise fast, decay slow
_RISE_FACTOR = 0.75  # snappy but not instant
_DECAY_FACTOR = 0.85  # faster falloff for more responsive feel

# Fade timing
_FADE_IN_S = 0.08
_FADE_OUT_S = 0.2


class GlowOverlay(NSObject):
    """Manages a screen-border glow window driven by audio amplitude."""

    def initWithScreen_(self, screen: NSScreen | None = None):
        self = objc.super(GlowOverlay, self).init()
        if self is None:
            return None

        self._screen = screen or NSScreen.mainScreen()
        self._window: NSWindow | None = None
        self._glow_layer: CAShapeLayer | None = None
        self._smoothed_amplitude = 0.0
        self._visible = False
        self._update_count = 0
        return self

    def setup(self) -> None:
        """Create the overlay window and glow layer."""
        frame = self._screen.frame()

        # Borderless, transparent, non-activating window
        self._window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, 0, 2, False  # NSWindowStyleMaskBorderless, NSBackingStoreBuffered
        )
        self._window.setLevel_(25)  # NSStatusWindowLevel + 1
        self._window.setOpaque_(False)
        self._window.setBackgroundColor_(NSColor.clearColor())
        self._window.setIgnoresMouseEvents_(True)
        self._window.setHasShadow_(False)
        self._window.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )

        # Content view must be layer-backed for Core Animation
        content = self._window.contentView()
        content.setWantsLayer_(True)

        w, h = frame.size.width, frame.size.height

        glow_color = NSColor.colorWithSRGBRed_green_blue_alpha_(
            _GLOW_COLOR[0], _GLOW_COLOR[1], _GLOW_COLOR[2], 1.0
        )

        # ── Container layer: holds shadow + masked fill ──────────
        # We control opacity on this layer to drive the whole effect.
        self._glow_layer = CALayer.alloc().init()
        self._glow_layer.setFrame_(((0, 0), (w, h)))
        self._glow_layer.setOpacity_(0.0)

        # ── Shadow-casting shape: thick border, full opacity ─────
        # This layer is a child that casts the soft bloom shadow.
        # Its own fill is hidden by the mask below — only its shadow is visible.
        shadow_shape = CAShapeLayer.alloc().init()

        outer = CGPathCreateWithRoundedRect(
            ((0, 0), (w, h)), _CORNER_RADIUS, _CORNER_RADIUS, None
        )
        inner = CGPathCreateWithRoundedRect(
            ((_GLOW_WIDTH, _GLOW_WIDTH),
             (w - 2 * _GLOW_WIDTH, h - 2 * _GLOW_WIDTH)),
            max(_CORNER_RADIUS - _GLOW_WIDTH, 0),
            max(_CORNER_RADIUS - _GLOW_WIDTH, 0),
            None,
        )

        from Quartz import CGPathCreateMutableCopy, CGPathAddPath
        combined = CGPathCreateMutableCopy(outer)
        CGPathAddPath(combined, None, inner)

        shadow_shape.setPath_(combined)
        shadow_shape.setFillRule_(kCAFillRuleEvenOdd)
        shadow_shape.setFillColor_(glow_color.CGColor())

        # Shadow bloom — the main visual
        shadow_shape.setShadowColor_(glow_color.CGColor())
        shadow_shape.setShadowOffset_((0, 0))
        shadow_shape.setShadowRadius_(_GLOW_SHADOW_RADIUS)
        shadow_shape.setShadowOpacity_(1.0)

        self._glow_layer.addSublayer_(shadow_shape)

        # Shape fill nearly transparent — just enough for CA to cast shadow
        shadow_shape.setFillColor_(
            glow_color.colorWithAlphaComponent_(0.05).CGColor()
        )

        # Add 4 gradient layers for the visible feathered edge glow.
        # Exponential-style falloff: bright at edge, drops fast, long subtle tail.
        # Use NSColor objects (not CGColor) — PyObjC bridges these correctly
        # for CAGradientLayer, unlike raw CGColorRef pointers.
        edge_nscolor = glow_color
        mid_nscolor = glow_color.colorWithAlphaComponent_(0.25)
        faint_nscolor = glow_color.colorWithAlphaComponent_(0.06)
        clear_nscolor = NSColor.colorWithSRGBRed_green_blue_alpha_(0, 0, 0, 0)

        # CAGradientLayer wants CGColorRef — extract via id bridge
        colors = [
            edge_nscolor.CGColor(),
            mid_nscolor.CGColor(),
            faint_nscolor.CGColor(),
            clear_nscolor.CGColor(),
        ]
        locations = [0.0, 0.15, 0.4, 1.0]

        grad_depth = _GLOW_WIDTH * 4  # gradient extends 4x border width

        edges = [
            # (origin, size, start_point, end_point)
            ((0, 0), (w, grad_depth), (0.5, 0.0), (0.5, 1.0)),          # bottom
            ((0, h - grad_depth), (w, grad_depth), (0.5, 1.0), (0.5, 0.0)),  # top
            ((0, 0), (grad_depth, h), (0.0, 0.5), (1.0, 0.5)),          # left
            ((w - grad_depth, 0), (grad_depth, h), (1.0, 0.5), (0.0, 0.5)),  # right
        ]
        for origin, size, start, end in edges:
            g = CAGradientLayer.alloc().init()
            g.setFrame_((origin, size))
            g.setColors_(colors)
            g.setLocations_(locations)
            g.setStartPoint_(start)
            g.setEndPoint_(end)
            self._glow_layer.addSublayer_(g)

        content.layer().addSublayer_(self._glow_layer)
        logger.info("Glow overlay created (%.0fx%.0f, border=%.0f, shadow=%.0f)",
                     w, h, _GLOW_WIDTH, _GLOW_SHADOW_RADIUS)

    def show(self) -> None:
        """Show the glow window with a faint base opacity."""
        if self._window is None:
            return
        self._visible = True
        self._smoothed_amplitude = 0.0
        self._update_count = 0
        self._glow_layer.setOpacity_(_GLOW_BASE_OPACITY)
        self._window.orderFrontRegardless()
        logger.info("Glow show")

    def hide(self) -> None:
        """Hide the glow window."""
        if self._window is None:
            return
        self._visible = False
        self._glow_layer.setOpacity_(0.0)
        self._window.orderOut_(None)
        logger.info("Glow hide (received %d amplitude updates)", self._update_count)

    def update_amplitude(self, rms: float) -> None:
        """Update glow intensity from an RMS amplitude value (0.0–1.0).

        Must be called on the main thread.
        """
        if not self._visible or self._glow_layer is None:
            return

        self._update_count += 1

        # Smooth: rise fast, decay slow
        if rms > self._smoothed_amplitude:
            self._smoothed_amplitude += (rms - self._smoothed_amplitude) * _RISE_FACTOR
        else:
            self._smoothed_amplitude *= _DECAY_FACTOR

        # Map smoothed amplitude to opacity range [base, max]
        # Speech RMS is typically 0.01–0.10, so multiply up to fill the range
        amplitude_opacity = self._smoothed_amplitude * 18.0
        opacity = _GLOW_BASE_OPACITY + min(amplitude_opacity, 1.0) * (_GLOW_MAX_OPACITY - _GLOW_BASE_OPACITY)

        self._glow_layer.setOpacity_(opacity)

        # Log first few updates and then periodically to verify pipeline
        if self._update_count <= 3 or self._update_count % 50 == 0:
            logger.info("Glow amplitude: rms=%.4f smoothed=%.4f opacity=%.3f (update #%d)",
                        rms, self._smoothed_amplitude, opacity, self._update_count)
