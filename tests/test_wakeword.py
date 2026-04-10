import sys
import threading
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
        assert not hasattr(listener, "_thread")

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

    def test_stop_does_not_delete_porcupine_until_active_callback_finishes(self):
        class BlockingPorcupine:
            def __init__(self) -> None:
                self.entered = threading.Event()
                self.release = threading.Event()
                self.deleted = threading.Event()

            def process(self, pcm):
                self.entered.set()
                self.release.wait(timeout=1.0)
                return -1

            def delete(self):
                self.deleted.set()

        listener = WakeWordListener(access_key="test", keywords=["computer"])
        stream = MagicMock()
        porcupine = BlockingPorcupine()
        listener._running = True
        listener._stream = stream
        listener._porcupine = porcupine

        pcm = np.array([[1], [2], [3]], dtype=np.int16)
        callback_thread = threading.Thread(
            target=listener._audio_callback,
            args=(pcm, 3, None, None),
        )
        callback_thread.start()
        assert porcupine.entered.wait(timeout=1.0)

        stop_thread = threading.Thread(target=listener.stop)
        stop_thread.start()

        assert not porcupine.deleted.wait(timeout=0.1)

        porcupine.release.set()
        callback_thread.join(timeout=1.0)
        stop_thread.join(timeout=1.0)

        assert porcupine.deleted.is_set()
        assert listener._running is False
        assert listener._stream is None
        assert listener._porcupine is None

    def test_stop_aborts_and_closes_stream_and_clears_state(self):
        listener = WakeWordListener(access_key="test", keywords=["computer"])
        events: list[str] = []
        stream = MagicMock()
        stream.abort.side_effect = lambda: events.append("abort")
        stream.close.side_effect = lambda: events.append("close")
        porcupine = MagicMock()
        listener._running = True
        listener._stream = stream
        listener._porcupine = porcupine

        listener.stop()

        assert events == ["abort", "close"]
        porcupine.delete.assert_called_once_with()
        assert listener._running is False
        assert listener._stream is None
        assert not hasattr(listener, "_thread")
        assert listener._porcupine is None

    def test_stop_still_cleans_up_if_stream_abort_fails(self):
        listener = WakeWordListener(access_key="test", keywords=["computer"])
        stream = MagicMock()
        stream.abort.side_effect = RuntimeError("abort failed")
        stream.close.side_effect = RuntimeError("close failed")
        porcupine = MagicMock()
        listener._running = True
        listener._stream = stream
        listener._porcupine = porcupine

        listener.stop()

        porcupine.delete.assert_called_once_with()
        assert listener._running is False
        assert listener._stream is None
        assert not hasattr(listener, "_thread")
        assert listener._porcupine is None
