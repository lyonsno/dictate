"""Perceptasia Throughglass Graft.

This is the first clean Spoke-hosted consumer for Perceptasia as a stack
surface.  The provider is provisional: Spoke owns the window and optical
request contract, while the current Perceptasia localhost viewer is only the
first content source behind that contract.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path

import objc
from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSPanel,
    NSScreen,
    NSTextField,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowCollectionBehaviorStationary,
    NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import NSMakeRect, NSObject

from .optical_field import (
    OpticalFieldBounds,
    OpticalFieldMotionIntent,
    OpticalFieldPresentation,
    OpticalFieldProfileRef,
    OpticalFieldRequest,
    OpticalFieldSignal,
    compile_placeholder_shell_config,
)

logger = logging.getLogger(__name__)

_CLIENT_ID = "perceptasia.throughglass"
_DEFAULT_URL = "http://localhost:8742"
_DEFAULT_WIDTH = 980.0
_DEFAULT_HEIGHT = 560.0
_MIN_MARGIN = 32.0

_NSWindowStyleMaskClosable = 1 << 1
_NSWindowStyleMaskResizable = 1 << 3
_NSWindowStyleMaskUtilityWindow = 1 << 4


@dataclass(frozen=True)
class PerceptasiaThroughglassManifest:
    """Spoke-owned provider contract for a Perceptasia stack surface."""

    schema: str = "spoke.perceptasia-throughglass.provider.v0"
    provider: str = "perceptasia"
    url: str = _DEFAULT_URL
    scene_url: str = f"{_DEFAULT_URL}/scene.json"
    selection_path: str = str(Path.home() / ".local" / "state" / "perceptasia" / "selection.json")

    @classmethod
    def from_env(cls) -> "PerceptasiaThroughglassManifest":
        url = os.environ.get("SPOKE_PERCEPTASIA_THROUGHGLASS_URL", _DEFAULT_URL).rstrip("/")
        return cls(
            url=url,
            scene_url=os.environ.get(
                "SPOKE_PERCEPTASIA_THROUGHGLASS_SCENE_URL",
                f"{url}/scene.json",
            ),
            selection_path=os.environ.get(
                "SPOKE_PERCEPTASIA_SELECTION_PATH",
                str(Path.home() / ".local" / "state" / "perceptasia" / "selection.json"),
            ),
        )


def build_perceptasia_optical_request(
    bounds: OpticalFieldBounds,
    *,
    state: str = "rest",
    visible: bool = True,
    brightness: float = 0.18,
) -> OpticalFieldRequest:
    """Build the primitive-level sibling request for the Throughglass surface."""

    return OpticalFieldRequest(
        caller_id=_CLIENT_ID,
        continuity_key=_CLIENT_ID,
        bounds=bounds,
        content_frame=bounds,
        role="hud",
        state=state,  # type: ignore[arg-type]
        presentation=OpticalFieldPresentation(layer="hud", order=42),
        presentation_layer="hud",
        layout_recipe="perceptasia-throughglass",
        motion=OpticalFieldMotionIntent(strategy="continuous", urgency="normal"),
        continuity="preserve_identity",
        profile=OpticalFieldProfileRef(
            base="agent_card",
            params={
                "corner_radius_frac": 0.20,
                "core_magnification": 1.025,
                "band_width_frac": 0.045,
                "tail_width_frac": 0.030,
                "ring_amplitude_frac": 0.035,
                "tail_amplitude_frac": 0.012,
                "bleed_zone_frac": 0.58,
                "exterior_mix_frac": 0.10,
                "mip_blur_strength": 0.55,
            },
        ),
        signals=(
            OpticalFieldSignal("background_luminance", brightness),
            OpticalFieldSignal("text_contrast_bias", 0.55),
            OpticalFieldSignal("ridge_emphasis", 0.38),
        ),
        visible=visible,
        z_index=4,
    )


def compile_perceptasia_shell_config(
    bounds: OpticalFieldBounds,
    *,
    state: str = "rest",
    visible: bool = True,
) -> dict:
    request = build_perceptasia_optical_request(bounds, state=state, visible=visible)
    config = compile_placeholder_shell_config(request)
    config["visible"] = bool(visible and state != "hidden")
    return config


class PerceptasiaThroughglassGraft(NSObject):
    """Non-activating Spoke window carrying the Perceptasia viewer."""

    def initWithCompositorRegistry_(self, registry):
        self = objc.super(PerceptasiaThroughglassGraft, self).init()
        if self is None:
            return None
        self._registry = registry
        self._host = None
        self._panel = None
        self._content_view = None
        self._visible = False
        self._manifest = PerceptasiaThroughglassManifest.from_env()
        return self

    def setup(self) -> None:
        if self._panel is not None:
            return
        screen = NSScreen.mainScreen()
        screen_frame = screen.visibleFrame() if screen is not None else NSMakeRect(0, 0, 1440, 900)
        x, y, width, height = _default_panel_rect(screen_frame)
        panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, width, height),
            _NSWindowStyleMaskClosable
            | _NSWindowStyleMaskResizable
            | _NSWindowStyleMaskUtilityWindow
            | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered,
            False,
        )
        panel.setTitle_("Perceptasia Throughglass Graft")
        panel.setLevel_(1000)
        panel.setOpaque_(False)
        panel.setHasShadow_(False)
        panel.setBackgroundColor_(NSColor.clearColor())
        panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        panel.setFloatingPanel_(True)
        panel.setBecomesKeyOnlyIfNeeded_(True)

        content = _make_content_view(self._manifest.url, width, height)
        panel.contentView().addSubview_(content)
        self._panel = panel
        self._content_view = content

    def show(self) -> None:
        if self._panel is None:
            self.setup()
        if self._panel is None:
            return
        self._panel.orderFrontRegardless()
        self._visible = True
        self._publish("materialize")
        self._publish("rest")

    def hide(self) -> None:
        self._visible = False
        self._publish("dismiss")
        self._publish("hidden", visible=False)
        if self._panel is not None:
            self._panel.orderOut_(None)

    def toggle(self) -> None:
        if self._visible:
            self.hide()
        else:
            self.show()

    def cleanup(self) -> None:
        self.hide()
        if self._host is not None:
            release = getattr(self._host, "release_client", None)
            if callable(release):
                release(_CLIENT_ID)
        self._panel = None
        self._content_view = None

    def _bounds(self) -> OpticalFieldBounds:
        if self._panel is None:
            return OpticalFieldBounds(0.0, 0.0, _DEFAULT_WIDTH, _DEFAULT_HEIGHT)
        frame = self._panel.frame()
        return OpticalFieldBounds(
            x=float(frame.origin.x),
            y=float(frame.origin.y),
            width=float(frame.size.width),
            height=float(frame.size.height),
        )

    def _publish(self, state: str, *, visible: bool = True) -> bool:
        if self._registry is None or self._panel is None or self._content_view is None:
            return False
        if self._host is None:
            host_for_screen = getattr(self._registry, "host_for_screen", None)
            if not callable(host_for_screen):
                return False
            self._host = host_for_screen(NSScreen.mainScreen())
        config = compile_perceptasia_shell_config(self._bounds(), state=state, visible=visible)
        if not getattr(self, "_client_registered", False):
            added = self._host.add_client(_CLIENT_ID, self._panel, self._content_view, config)
            self._client_registered = bool(added)
            return bool(added)
        return bool(self._host.update_client_config(_CLIENT_ID, config))


def _default_panel_rect(frame) -> tuple[float, float, float, float]:
    width = min(_DEFAULT_WIDTH, max(480.0, float(frame.size.width) - 2 * _MIN_MARGIN))
    height = min(_DEFAULT_HEIGHT, max(320.0, float(frame.size.height) - 2 * _MIN_MARGIN))
    x = float(frame.origin.x) + (float(frame.size.width) - width) * 0.5
    y = float(frame.origin.y) + (float(frame.size.height) - height) * 0.5
    return x, y, width, height


def _make_content_view(url: str, width: float, height: float):
    try:
        from Foundation import NSURL, NSURLRequest
        from WebKit import WKWebView

        view = WKWebView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        request = NSURLRequest.requestWithURL_(NSURL.URLWithString_(url))
        view.loadRequest_(request)
        return view
    except Exception:
        label = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        label.setStringValue_(f"Perceptasia provider: {url}")
        label.setBezeled_(False)
        label.setDrawsBackground_(True)
        label.setBackgroundColor_(NSColor.colorWithWhite_alpha_(0.08, 0.88))
        label.setTextColor_(NSColor.colorWithWhite_alpha_(0.86, 1.0))
        label.setEditable_(False)
        label.setSelectable_(True)
        return label
