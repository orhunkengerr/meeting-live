"""Capture system audio (the other side) and the microphone (you) on Windows.

Both streams are converted to 16 kHz mono float32, the format Whisper expects,
and pushed onto a single queue as AudioChunk objects tagged with their source.
"""

import queue
import time
from dataclasses import dataclass

import numpy as np
import pyaudiowpatch as pyaudio

TARGET_RATE = 16000


@dataclass
class AudioChunk:
    source: str          # "them" (system audio) or "me" (microphone)
    samples: np.ndarray  # float32 mono, 16 kHz, range -1..1
    timestamp: float     # time.time() when the chunk arrived


def _to_mono_16k(data: bytes, channels: int, rate: int) -> np.ndarray:
    x = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
    if channels > 1:
        x = x.reshape(-1, channels).mean(axis=1)
    if rate != TARGET_RATE:
        n = int(round(len(x) * TARGET_RATE / rate))
        x = np.interp(np.linspace(0, len(x), n, endpoint=False), np.arange(len(x)), x)
    return x.astype(np.float32)


def _devices(pa: pyaudio.PyAudio, source: str):
    """WASAPI devices for a source: speaker loopbacks for "them", microphones for "me"."""
    if source == "them":
        yield from pa.get_loopback_device_info_generator()
        return
    wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)["index"]
    for i in range(pa.get_device_count()):
        device = pa.get_device_info_by_index(i)
        if device["hostApi"] == wasapi and device["maxInputChannels"] > 0 and not device.get("isLoopbackDevice"):
            yield device


def _find(pa: pyaudio.PyAudio, source: str, name: str) -> dict:
    if name == "default":
        if source == "them":
            return pa.get_default_wasapi_loopback()
        wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        return pa.get_device_info_by_index(wasapi["defaultInputDevice"])
    for device in _devices(pa, source):
        if device["name"] == name:
            return device
    raise RuntimeError(f"audio device not found: {name}")


def list_devices() -> dict[str, list[str]]:
    """Device names to choose from, keyed by source."""
    pa = pyaudio.PyAudio()
    try:
        return {source: [d["name"] for d in _devices(pa, source)] for source in ("them", "me")}
    finally:
        pa.terminate()


class AudioCapture:
    """Opens the chosen speaker loopback and/or microphone via WASAPI.

    sources maps "them" and/or "me" to a device name, or "default".
    Leave a source out to not capture it.
    """

    def __init__(self, out: queue.Queue, sources: dict[str, str], block_ms: int = 100):
        self.out = out
        self.sources = sources
        self.block_ms = block_ms
        self._pa = None
        self._streams = []

    def _open(self, device: dict, source: str):
        channels = device["maxInputChannels"]
        rate = int(device["defaultSampleRate"])

        def callback(in_data, frame_count, time_info, status):
            self.out.put(AudioChunk(source, _to_mono_16k(in_data, channels, rate), time.time()))
            return (None, pyaudio.paContinue)

        stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=channels,
            rate=rate,
            input=True,
            input_device_index=device["index"],
            frames_per_buffer=int(rate * self.block_ms / 1000),
            stream_callback=callback,
        )
        self._streams.append(stream)
        return device["name"]

    def start(self) -> dict:
        """Start capturing. Returns the device names in use, keyed by source."""
        self._pa = pyaudio.PyAudio()
        try:
            return {source: self._open(_find(self._pa, source, name), source) for source, name in self.sources.items()}
        except Exception:
            self.stop()
            raise

    def stop(self):
        for stream in self._streams:
            stream.stop_stream()
            stream.close()
        self._streams.clear()
        if self._pa:
            self._pa.terminate()
            self._pa = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()


if __name__ == "__main__":
    # Quick check: list devices, then play something and talk for 5 seconds and see the levels.
    for source, names in list_devices().items():
        print(f"{source}: {names}")
    q = queue.Queue()
    capture = AudioCapture(q, {"them": "default", "me": "default"})
    for source, name in capture.start().items():
        print(f"{source:>4}: {name}")
    time.sleep(5)
    capture.stop()

    levels = {"them": [], "me": []}
    while not q.empty():
        chunk = q.get()
        levels[chunk.source].append(float(np.sqrt(np.mean(chunk.samples ** 2))))
    for source, values in levels.items():
        if values:
            print(f"{source:>4}: {len(values)} chunks, peak level {max(values):.3f}")
