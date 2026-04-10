from unittest.mock import MagicMock, patch

from spoke.handsfree import HandsFreeController, HandsFreeState


class TestHandsFreeControllerWakeWords:
    def test_sleep_wake_word_disables_handsfree_while_listening(self):
        controller = HandsFreeController(delegate=MagicMock())
        controller._state = HandsFreeState.LISTENING
        controller.disable = MagicMock()

        controller.handle_wake_word("sleep")

        controller.disable.assert_called_once_with()

    def test_sleep_wake_word_disables_handsfree_while_dictating(self):
        controller = HandsFreeController(delegate=MagicMock())
        controller._state = HandsFreeState.DICTATING
        controller.disable = MagicMock()

        controller.handle_wake_word("sleep")

        controller.disable.assert_called_once_with()

    def test_segment_transcription_of_sleep_word_routes_to_wake_handler(self):
        delegate = MagicMock()
        delegate._client.transcribe.return_value = "Terminator"
        controller = HandsFreeController(delegate=delegate)
        controller._state = HandsFreeState.DICTATING

        class ImmediateThread:
            def __init__(self, target=None, args=(), kwargs=None, **_kwargs):
                self._target = target
                self._args = args
                self._kwargs = kwargs or {}

            def start(self):
                if self._target is not None:
                    self._target(*self._args, **self._kwargs)

        with patch("spoke.handsfree.threading.Thread", side_effect=lambda *args, **kwargs: ImmediateThread(*args, **kwargs)):
            controller._on_segment(b"wav")

        delegate.performSelectorOnMainThread_withObject_waitUntilDone_.assert_called_once_with(
            "handleWakeWord:", {"role": "sleep"}, False,
        )

    def test_segment_transcription_of_sleep_word_ignores_case_and_punctuation(self):
        delegate = MagicMock()
        delegate._client.transcribe.return_value = "  TeRmInAtOr!? "
        controller = HandsFreeController(delegate=delegate)
        controller._state = HandsFreeState.DICTATING

        class ImmediateThread:
            def __init__(self, target=None, args=(), kwargs=None, **_kwargs):
                self._target = target
                self._args = args
                self._kwargs = kwargs or {}

            def start(self):
                if self._target is not None:
                    self._target(*self._args, **self._kwargs)

        with patch("spoke.handsfree.threading.Thread", side_effect=lambda *args, **kwargs: ImmediateThread(*args, **kwargs)):
            controller._on_segment(b"wav")

        delegate.performSelectorOnMainThread_withObject_waitUntilDone_.assert_called_once_with(
            "handleWakeWord:", {"role": "sleep"}, False,
        )
