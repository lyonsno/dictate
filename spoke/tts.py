"""Text-to-speech via local Voxtral or a remote speech sidecar.

Loads a local Voxtral TTS model lazily or fetches synthesized audio from
an OpenAI-compatible remote sidecar, then plays audio through
sounddevice. Designed to be driven from the command-completion pathway in
__main__.py — speak_async() returns immediately, running synthesis and
playback on a background thread.
"""

from __future__ import annotations

import io
import logging
import os
import threading
import wave
from typing import Callable, Optional

import httpx
import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

_DEFAULT_MODEL_ID = "mlx-community/Voxtral-4B-TTS-2603-mlx-4bit"
_DEFAULT_VOICE = "casual_female"
_DEFAULT_TEMPERATURE = 0.5
_DEFAULT_TOP_K = 50
_DEFAULT_TOP_P = 0.95
_DEFAULT_TTS_URL = "http://localhost:8002"


def tts_load(model_id: str):
    """Load a Voxtral TTS model.  Separated for easy patching in tests."""
    from mlx_audio.tts import load
    return load(model_id)


class _PlaybackTTSClient:
    """Shared playback, cancellation, and async helpers for TTS clients."""

    def __init__(self) -> None:
        self._cancelled = False
        self._stream: sd.OutputStream | None = None
        self._last_chunk: np.ndarray | None = None

    def _play_audio(
        self,
        audio: np.ndarray,
        sample_rate: int,
        amplitude_callback: Callable[[float], None] | None = None,
    ) -> None:
        """Play float32 audio locally, emitting optional RMS updates."""
        if self._cancelled:
            return
        if audio.size == 0:
            if amplitude_callback is not None:
                amplitude_callback(0.0)
            return
        if audio.ndim == 1:
            audio = audio.reshape(-1, 1)

        chunk_size = int(sample_rate * 0.064)
        done = threading.Event()
        stream = sd.OutputStream(
            samplerate=sample_rate,
            channels=audio.shape[1],
            dtype="float32",
            finished_callback=lambda: done.set(),
        )
        self._stream = stream
        self._last_chunk = None
        stream.start()

        try:
            offset = 0
            while offset < len(audio):
                if self._cancelled:
                    break
                end = min(offset + chunk_size, len(audio))
                chunk = audio[offset:end]
                self._last_chunk = chunk
                stream.write(chunk)
                if amplitude_callback is not None:
                    rms = float(np.sqrt(np.mean(chunk ** 2)))
                    amplitude_callback(rms)
                offset = end

            while not done.is_set():
                if self._cancelled:
                    break
                done.wait(timeout=0.05)

            if self._cancelled and not done.is_set() and self._last_chunk is not None:
                fade_samples = int(sample_rate * 0.05)
                last_amp = float(np.mean(np.abs(self._last_chunk[-1:])))
                fade_ramp = np.linspace(last_amp, 0.0, fade_samples, dtype=np.float32).reshape(-1, 1)
                try:
                    stream.write(fade_ramp)
                except Exception:
                    pass
        finally:
            stream.stop()
            stream.close()
            self._stream = None
            self._last_chunk = None

        if amplitude_callback is not None:
            amplitude_callback(0.0)

    def speak_async(
        self,
        text: str,
        amplitude_callback: Callable[[float], None] | None = None,
        done_callback: Callable[[], None] | None = None,
    ) -> threading.Thread:
        """Generate and play speech on a background daemon thread."""
        self._cancelled = False

        def _run():
            self.speak(text, amplitude_callback=amplitude_callback)
            if done_callback is not None:
                done_callback()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return t

    def cancel(self) -> None:
        """Cancel any in-flight or future speak() call."""
        self._cancelled = True


class TTSClient(_PlaybackTTSClient):
    """Lazy-loading local Voxtral TTS client with cancellation support."""

    def __init__(
        self,
        model_id: str = _DEFAULT_MODEL_ID,
        voice: str = _DEFAULT_VOICE,
        temperature: float = _DEFAULT_TEMPERATURE,
        top_k: int = _DEFAULT_TOP_K,
        top_p: float = _DEFAULT_TOP_P,
        gpu_lock: threading.Lock | None = None,
    ):
        super().__init__()
        self._model_id = model_id
        self._voice = voice
        self._temperature = temperature
        self._top_k = top_k
        self._top_p = top_p
        self._model = None
        self._gpu_lock = gpu_lock

    @classmethod
    def from_env(cls, gpu_lock: threading.Lock | None = None) -> Optional["TTSClient | RemoteTTSClient"]:
        """Create a TTS client from environment variables, or None if disabled.

        Set SPOKE_TTS_VOICE to enable TTS (e.g. "casual_female").
        Optionally set SPOKE_TTS_MODEL to override the default model.
        Set SPOKE_TTS_URL to route synthesis to a remote OpenAI-compatible
        /v1/audio/speech sidecar while keeping playback local.
        """
        voice = os.environ.get("SPOKE_TTS_VOICE")
        if not voice:
            return None
        base_url = os.environ.get("SPOKE_TTS_URL", "").rstrip("/")
        model_id = os.environ.get("SPOKE_TTS_MODEL", _DEFAULT_MODEL_ID)
        temperature = float(os.environ.get("SPOKE_TTS_TEMPERATURE", str(_DEFAULT_TEMPERATURE)))
        top_k = int(os.environ.get("SPOKE_TTS_TOP_K", str(_DEFAULT_TOP_K)))
        top_p = float(os.environ.get("SPOKE_TTS_TOP_P", str(_DEFAULT_TOP_P)))
        if base_url:
            return RemoteTTSClient(base_url=base_url, model_id=model_id, voice=voice)
        return cls(model_id=model_id, voice=voice, temperature=temperature, top_k=top_k, top_p=top_p, gpu_lock=gpu_lock)

    def _ensure_model(self):
        """Load the model on first use."""
        if self._model is None:
            logger.info("Loading TTS model %s …", self._model_id)
            self._model = tts_load(self._model_id)
            logger.info("TTS model loaded.")

    def warm(self) -> None:
        """Pre-load the model in a background thread so first speak() is fast."""
        def _warm():
            from contextlib import nullcontext
            lock_ctx = self._gpu_lock if self._gpu_lock is not None else nullcontext()
            with lock_ctx:
                self._ensure_model()
        threading.Thread(target=_warm, daemon=True).start()

    def speak(
        self,
        text: str,
        amplitude_callback: Callable[[float], None] | None = None,
    ) -> None:
        """Generate speech and play it synchronously.  Blocks until done.

        Holds gpu_lock during model.generate() to prevent concurrent MLX
        inference (which crashes Metal).  Releases the lock before audio
        playback so Whisper can proceed while audio plays.

        If amplitude_callback is provided, it is called with the RMS value
        of each ~64ms audio chunk during playback (same interface as the
        microphone amplitude callback used by the glow overlay).
        """
        if not text:
            return
        if self._cancelled:
            return

        from contextlib import nullcontext

        lock_ctx = self._gpu_lock if self._gpu_lock is not None else nullcontext()

        with lock_ctx:
            self._ensure_model()
            if self._cancelled:
                return
            # Generate audio while holding the GPU lock
            results = []
            for result in self._model.generate(
                text=text,
                voice=self._voice,
                temperature=self._temperature,
                top_k=self._top_k,
                top_p=self._top_p,
            ):
                if self._cancelled:
                    return
                results.append(result)
        # GPU lock released — play audio without blocking Whisper
        for result in results:
            if self._cancelled:
                return
            audio = np.array(result.audio, dtype=np.float32)
            self._play_audio(audio, result.sample_rate, amplitude_callback=amplitude_callback)


class RemoteTTSClient(_PlaybackTTSClient):
    """HTTP-backed TTS client for a remote OpenAI-compatible speech sidecar."""

    def __init__(
        self,
        base_url: str = _DEFAULT_TTS_URL,
        model_id: str = _DEFAULT_MODEL_ID,
        voice: str = _DEFAULT_VOICE,
        timeout: float = 120.0,
    ) -> None:
        super().__init__()
        self._base_url = base_url.rstrip("/")
        self._url = f"{self._base_url}/v1/audio/speech"
        self._model_id = model_id
        self._voice = voice
        self._client = httpx.Client(timeout=timeout)

    def warm(self) -> None:
        """Remote speech is ready once the HTTP client exists."""
        return None

    def _decode_wav(self, wav_bytes: bytes) -> tuple[np.ndarray, int]:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            sample_rate = wav_file.getframerate()
            frames = wav_file.readframes(wav_file.getnframes())

        if sample_width == 1:
            audio = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
        elif sample_width == 2:
            audio = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        elif sample_width == 4:
            audio = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
        else:
            raise ValueError(f"Unsupported WAV sample width: {sample_width}")

        return audio.reshape(-1, channels), sample_rate

    def speak(
        self,
        text: str,
        amplitude_callback: Callable[[float], None] | None = None,
    ) -> None:
        if not text:
            return
        if self._cancelled:
            return

        response = self._client.post(
            self._url,
            json={
                "model": self._model_id,
                "voice": self._voice,
                "input": text,
                "response_format": "wav",
            },
        )
        response.raise_for_status()
        if self._cancelled:
            return
        audio, sample_rate = self._decode_wav(response.content)
        self._play_audio(audio, sample_rate, amplitude_callback=amplitude_callback)
