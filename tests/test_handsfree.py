from unittest.mock import MagicMock

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
