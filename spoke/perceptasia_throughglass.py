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
import urllib.error
import urllib.request

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
_DISCOVERY_PORTS = (8742, 8753, 8754, 8755, 8764, 8797, 8798, 8799, 8896)

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
        requested_url = os.environ.get("SPOKE_PERCEPTASIA_THROUGHGLASS_URL", _DEFAULT_URL).rstrip("/")
        url = _resolve_provider_url(requested_url)
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
        logger.info("Perceptasia Throughglass: setup begin url=%s", self._manifest.url)
        provider_reachable = _is_provider_reachable(self._manifest.url)
        if not provider_reachable:
            logger.warning(
                "Perceptasia Throughglass: provider unavailable url=%s",
                self._manifest.url,
            )
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
        # Visual-only grafts must not steal desktop clicks unless an input mode opts in.
        panel.setIgnoresMouseEvents_(True)
        panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorStationary
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        panel.setFloatingPanel_(True)
        panel.setBecomesKeyOnlyIfNeeded_(True)

        content = (
            _make_content_view(self._manifest.url, width, height)
            if provider_reachable
            else _make_provider_unavailable_view(self._manifest.url, width, height)
        )
        panel.contentView().addSubview_(content)
        self._panel = panel
        self._content_view = content
        logger.info(
            "Perceptasia Throughglass: setup complete x=%.1f y=%.1f w=%.1f h=%.1f",
            x,
            y,
            width,
            height,
        )

    def show(self) -> None:
        logger.info("Perceptasia Throughglass: show begin")
        if self._panel is None:
            self.setup()
        if self._panel is None:
            logger.warning("Perceptasia Throughglass: show aborted without panel")
            return
        self._panel.orderFrontRegardless()
        self._visible = True
        self.__publish_shell_state("materialize")
        self.__publish_shell_state("rest")
        logger.info("Perceptasia Throughglass: show complete")

    def hide(self) -> None:
        self._visible = False
        self.__publish_shell_state("dismiss")
        self.__publish_shell_state("hidden", visible=False)
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

    def __publish_shell_state(self, state: str, *, visible: bool = True) -> bool:
        if self._registry is None or self._panel is None or self._content_view is None:
            logger.info("Perceptasia Throughglass: publish skipped state=%s", state)
            return False
        if self._host is None:
            host_for_screen = getattr(self._registry, "host_for_screen", None)
            if not callable(host_for_screen):
                logger.info("Perceptasia Throughglass: registry has no host_for_screen")
                return False
            self._host = host_for_screen(NSScreen.mainScreen())
        config = compile_perceptasia_shell_config(self._bounds(), state=state, visible=visible)
        if not getattr(self, "_client_registered", False):
            added = self._host.add_client(_CLIENT_ID, self._panel, self._content_view, config)
            self._client_registered = bool(added)
            logger.info(
                "Perceptasia Throughglass: publish state=%s registered=%s",
                state,
                self._client_registered,
            )
            return bool(added)
        updated = bool(self._host.update_client_config(_CLIENT_ID, config))
        logger.info("Perceptasia Throughglass: publish state=%s updated=%s", state, updated)
        return updated


def _default_panel_rect(frame) -> tuple[float, float, float, float]:
    width = min(_DEFAULT_WIDTH, max(480.0, float(frame.size.width) - 2 * _MIN_MARGIN))
    height = min(_DEFAULT_HEIGHT, max(320.0, float(frame.size.height) - 2 * _MIN_MARGIN))
    x = float(frame.origin.x) + (float(frame.size.width) - width) * 0.5
    y = float(frame.origin.y) + (float(frame.size.height) - height) * 0.5
    return x, y, width, height


def _discovery_ports() -> tuple[int, ...]:
    raw = os.environ.get("SPOKE_PERCEPTASIA_THROUGHGLASS_DISCOVERY_PORTS", "")
    if not raw.strip():
        return _DISCOVERY_PORTS
    ports: list[int] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            ports.append(int(item))
        except ValueError:
            logger.warning("Perceptasia Throughglass: ignoring invalid discovery port %r", item)
    return tuple(ports) or _DISCOVERY_PORTS


def _candidate_provider_urls(requested_url: str) -> tuple[str, ...]:
    candidates = [requested_url.rstrip("/"), _DEFAULT_URL]
    candidates.extend(f"http://localhost:{port}" for port in _discovery_ports())
    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return tuple(unique)


def _is_provider_reachable(url: str, *, timeout: float = 0.35) -> bool:
    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            if not 200 <= status < 400:
                return False
            read = getattr(response, "read", None)
            if not callable(read):
                return True
            body = read(65536)
            if not body:
                return True
            marker = body.decode("utf-8", errors="ignore").lower()
            return "perceptasia" in marker or "scene.json" in marker
    except (OSError, urllib.error.URLError, ValueError):
        return False


def _resolve_provider_url(requested_url: str) -> str:
    for candidate in _candidate_provider_urls(requested_url):
        if _is_provider_reachable(candidate):
            if candidate != requested_url:
                logger.info(
                    "Perceptasia Throughglass: resolved provider %s from requested %s",
                    candidate,
                    requested_url,
                )
            return candidate
    return requested_url


def _make_content_view(url: str, width: float, height: float):
    try:
        from Foundation import NSURL, NSURLRequest
        from WebKit import WKWebView

        logger.info("Perceptasia Throughglass: creating WKWebView")
        view = WKWebView.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        request = NSURLRequest.requestWithURL_(NSURL.URLWithString_(url))
        view.loadRequest_(request)
        logger.info("Perceptasia Throughglass: WKWebView request loaded")
        return view
    except Exception:
        logger.warning("Perceptasia Throughglass: WKWebView unavailable, using fallback", exc_info=True)
        label = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
        label.setStringValue_(f"Perceptasia provider: {url}")
        label.setBezeled_(False)
        label.setDrawsBackground_(True)
        label.setBackgroundColor_(NSColor.colorWithWhite_alpha_(0.08, 0.88))
        label.setTextColor_(NSColor.colorWithWhite_alpha_(0.86, 1.0))
        label.setEditable_(False)
        label.setSelectable_(True)
        return label


def _make_provider_unavailable_view(url: str, width: float, height: float):
    label = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, width, height))
    label.setStringValue_(f"Perceptasia provider unavailable: {url}")
    label.setBezeled_(False)
    label.setDrawsBackground_(True)
    label.setBackgroundColor_(NSColor.colorWithWhite_alpha_(0.08, 0.88))
    label.setTextColor_(NSColor.colorWithWhite_alpha_(0.86, 1.0))
    label.setEditable_(False)
    label.setSelectable_(True)
    return label
