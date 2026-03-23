"""Tests for text injection via pasteboard + synthetic Cmd+V.

Requires PyObjC mocks since inject.py imports AppKit/Quartz at module level.
"""

from unittest.mock import MagicMock, call


class TestInjectText:
    """Test the inject_text() function."""

    def test_empty_text_is_noop(self, inject_module):
        """inject_text('') should do nothing."""
        AppKit = __import__("AppKit")
        inject_module.inject_text("")
        AppKit.NSPasteboard.generalPasteboard.assert_not_called()

    def test_sets_pasteboard_and_posts_cmd_v(self, inject_module):
        """Should set pasteboard to text and synthesize Cmd+V."""
        AppKit = __import__("AppKit")
        Quartz = __import__("Quartz")

        mock_pb = MagicMock()
        mock_pb.stringForType_.return_value = "original clipboard"
        AppKit.NSPasteboard.generalPasteboard.return_value = mock_pb

        inject_module.inject_text("hello world")

        # Pasteboard should be cleared and set
        mock_pb.clearContents.assert_called()
        mock_pb.setString_forType_.assert_called_with(
            "hello world", AppKit.NSPasteboardTypeString
        )

        # Should have posted keyboard events (Cmd+V down + up)
        assert Quartz.CGEventPost.call_count >= 2

    def test_saves_original_pasteboard(self, inject_module):
        """Should read original pasteboard string before overwriting."""
        AppKit = __import__("AppKit")

        mock_pb = MagicMock()
        mock_pb.stringForType_.return_value = "saved text"
        AppKit.NSPasteboard.generalPasteboard.return_value = mock_pb

        inject_module.inject_text("new text")

        # Should have read the original
        mock_pb.stringForType_.assert_called_with(AppKit.NSPasteboardTypeString)


class TestPostCmdV:
    """Test the synthetic keystroke generation."""

    def test_creates_keydown_and_keyup(self, inject_module):
        """Should create both keyDown and keyUp events for 'v'."""
        Quartz = __import__("Quartz")
        Quartz.CGEventCreateKeyboardEvent.reset_mock()
        Quartz.CGEventPost.reset_mock()

        inject_module._post_cmd_v()

        # Two events created: keyDown (True) and keyUp (False)
        calls = Quartz.CGEventCreateKeyboardEvent.call_args_list
        assert len(calls) == 2
        assert calls[0][0][1] == inject_module._V_KEYCODE  # keycode
        assert calls[0][0][2] is True   # keyDown
        assert calls[1][0][2] is False  # keyUp

        # Both events posted
        assert Quartz.CGEventPost.call_count == 2

    def test_sets_command_flag(self, inject_module):
        """Both events should have the Cmd modifier flag set."""
        Quartz = __import__("Quartz")
        Quartz.CGEventSetFlags.reset_mock()

        inject_module._post_cmd_v()

        # CGEventSetFlags called twice (once per event)
        assert Quartz.CGEventSetFlags.call_count == 2
        for c in Quartz.CGEventSetFlags.call_args_list:
            assert c[0][1] == Quartz.kCGEventFlagMaskCommand
