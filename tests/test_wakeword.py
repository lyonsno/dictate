import sys
import types
from unittest.mock import MagicMock, patch

import numpy as np

from spoke.wakeword import WakeWordListener


class TestWakeWordListenerStop:
    def test_start_uses_callback_stream_without_listener_thread(self, monkeypatch):
        porcupine = MagicMock()
        porcupine.frame_length = 512
        porcupine.sample_rate = 16000
        stream = MagicMock()
        monkeypatch.setitem(
            sys.modules,
            "pvporcupine",
            types.SimpleNamespace(create=MagicMock(return_value=porcupine)),
        )
        monkeypatch.setitem(
            sys.modules,
            "sounddevice",
            types.SimpleNamespace(InputStream=MagicMock(return_value=stream)),
        )
        listener = WakeWordListener(access_key="test", keywords=["computer"])

        with patch("spoke.wakeword.threading.Thread") as mock_thread:
            listener.start()

        callback = sys.modules["sounddevice"].InputStream.call_args.kwargs["callback"]
        assert callable(callback)
        stream.start.assert_called_once_with()
        mock_thread.assert_not_called()
        assert listener._stream is stream
        assert listener._thread is None

    def test_audio_callback_processes_frames_and_emits_detected_keyword(self):
        on_wake = MagicMock()
        porcupine = MagicMock()
        porcupine.process.return_value = 0
        listener = WakeWordListener(
            access_key="test",
            keywords=["computer"],
            on_wake=on_wake,
        )
        listener._porcupine = porcupine
        listener._running = True
        pcm = np.array([[1], [2], [3]], dtype=np.int16)

        listener._audio_callback(pcm, 3, None, None)

        np.testing.assert_array_equal(porcupine.process.call_args.args[0], pcm[:, 0])
        on_wake.assert_called_once_with("computer")

    def test_stop_aborts_and_closes_stream_before_join(self):
        listener = WakeWordListener(access_key="test", keywords=["computer"])
        events: list[str] = []
        stream = MagicMock()
        stream.abort.side_effect = lambda: events.append("abort")
        stream.close.side_effect = lambda: events.append("close")
        thread = MagicMock()
        thread.join.side_effect = lambda timeout=None: events.append("join")
        thread.is_alive.return_value = False
        porcupine = MagicMock()
        listener._running = True
        listener._stream = stream
        listener._thread = thread
        listener._porcupine = porcupine

        listener.stop()

        assert events[:3] == ["abort", "close", "join"]
        thread.join.assert_called_once_with(timeout=2.0)
        porcupine.delete.assert_called_once_with()
        assert listener._running is False
        assert listener._stream is None
        assert listener._thread is None
        assert listener._porcupine is None

    def test_stop_still_joins_and_cleans_up_if_stream_abort_fails(self):
        listener = WakeWordListener(access_key="test", keywords=["computer"])
        stream = MagicMock()
        stream.abort.side_effect = RuntimeError("abort failed")
        stream.close.side_effect = RuntimeError("close failed")
        thread = MagicMock()
        thread.is_alive.return_value = False
        porcupine = MagicMock()
        listener._running = True
        listener._stream = stream
        listener._thread = thread
        listener._porcupine = porcupine

        listener.stop()

        thread.join.assert_called_once_with(timeout=2.0)
        porcupine.delete.assert_called_once_with()
        assert listener._running is False
        assert listener._stream is None
        assert listener._thread is None
        assert listener._porcupine is None
