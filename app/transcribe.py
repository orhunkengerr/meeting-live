"""Turn the audio stream into sentences with Whisper.

Each source ("them", "me") gets its own segmenter that cuts the stream at
pauses. Finished segments are transcribed with faster-whisper. With the model
set to "auto", its size is picked from the GPU's memory.
"""

import queue
import subprocess
import threading
from collections import Counter, deque
from dataclasses import dataclass

import numpy as np
from faster_whisper import WhisperModel

from app.audio import TARGET_RATE, AudioChunk

# (minimum VRAM in MB, model). The first match wins.
GPU_TIERS = [(8000, "large-v3"), (4000, "medium"), (0, "small")]
CPU_MODEL = "base"

# With the language on "auto", it is locked once this many confident,
# long-enough sentences agree. Short replies like "OK" are too easy to misread.
LOCK_VOTES = 3
LOCK_MIN_SECONDS = 2.0
LOCK_MIN_PROBABILITY = 0.7


@dataclass
class Utterance:
    source: str    # "them" or "me"
    start: float   # time.time() of the first sample
    end: float
    text: str
    language: str  # two-letter code Whisper heard, e.g. "en"


def gpu_memory_mb() -> int | None:
    """Total memory of the largest NVIDIA GPU, or None when there is none."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout
        return max(int(line) for line in out.split())
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def pick_model(setting: str = "auto") -> tuple[str, str, str]:
    """Return (model, device, compute_type) for this machine."""
    vram = gpu_memory_mb()
    device, compute = ("cuda", "float16") if vram else ("cpu", "int8")
    if setting != "auto":
        return setting, device, compute
    if not vram:
        return CPU_MODEL, device, compute
    return next(model for mb, model in GPU_TIERS if vram >= mb), device, compute


class Segmenter:
    """Cuts one source's audio into utterances at pauses.

    Speech is anything louder than three times the background level. The
    background level follows quiet parts quickly and creeps up slowly during
    loud parts, so a constant hum stops counting as speech after a while.
    """

    def __init__(self, silence_ms=700, min_speech_ms=400, max_ms=15000, preroll_ms=300, min_level=0.008):
        self.silence_ms = silence_ms
        self.min_speech_ms = min_speech_ms
        self.max_ms = max_ms
        self.min_level = min_level
        self.preroll = deque(maxlen=max(1, preroll_ms // 100))
        self.noise = 0.003
        self._reset()

    def _reset(self):
        self.buf = []
        self.start = None
        self.speech_ms = 0.0
        self.silent_ms = 0.0
        self.total_ms = 0.0

    def feed(self, chunk: AudioChunk) -> tuple[float, float, np.ndarray] | None:
        """Add a chunk. Returns (start, end, audio) when an utterance ends."""
        samples = chunk.samples
        ms = len(samples) / TARGET_RATE * 1000
        level = float(np.sqrt(np.mean(samples ** 2))) if len(samples) else 0.0
        speaking = level > max(self.min_level, self.noise * 3)
        if speaking:
            self.noise *= 1.002
        else:
            self.noise += 0.05 * (level - self.noise)

        if self.start is None:
            if not speaking:
                self.preroll.append(samples)
                return None
            preroll_ms = sum(len(p) for p in self.preroll) / TARGET_RATE * 1000
            self.start = chunk.timestamp - preroll_ms / 1000
            self.buf = list(self.preroll)
            self.total_ms = preroll_ms
            self.preroll.clear()

        self.buf.append(samples)
        self.total_ms += ms
        if speaking:
            self.speech_ms += ms
            self.silent_ms = 0.0
        else:
            self.silent_ms += ms

        if self.silent_ms >= self.silence_ms or self.total_ms >= self.max_ms:
            start, audio, enough = self.start, np.concatenate(self.buf), self.speech_ms >= self.min_speech_ms
            self._reset()
            return (start, chunk.timestamp, audio) if enough else None
        return None


class Transcriber:
    def __init__(self, model: str = "auto", language: str | None = "en"):
        name, device, compute = pick_model(model)
        try:
            self.model = self._load(name, device, compute)
        except Exception:
            # CUDA libraries missing or GPU unusable: fall back to the CPU.
            if device == "cpu":
                raise
            name, device, compute = (CPU_MODEL if model == "auto" else name), "cpu", "int8"
            self.model = self._load(name, device, compute)
        self.description = f"{name} on {device}"
        self.language = None if language == "auto" else language
        self._votes = Counter()

    @staticmethod
    def _load(name: str, device: str, compute: str) -> WhisperModel:
        model = WhisperModel(name, device=device, compute_type=compute)
        # Warm up once so a broken GPU setup fails here, not mid-meeting.
        list(model.transcribe(np.zeros(TARGET_RATE, dtype=np.float32))[0])
        return model

    def transcribe(self, audio: np.ndarray) -> tuple[str, str]:
        """Return (text, language)."""
        segments, info = self.model.transcribe(
            audio,
            language=self.language,
            beam_size=1,
            condition_on_previous_text=False,
        )
        text = " ".join(s.text.strip() for s in segments if s.no_speech_prob < 0.6).strip()
        if (self.language is None and text and len(audio) >= LOCK_MIN_SECONDS * TARGET_RATE
                and info.language_probability >= LOCK_MIN_PROBABILITY):
            self._votes[info.language] += 1
            language, votes = self._votes.most_common(1)[0]
            if votes >= LOCK_VOTES:
                self.language = language
        return text, info.language

    def run(self, audio_q: queue.Queue, out_q: queue.Queue, stop: threading.Event):
        """Read AudioChunks until stop is set, put Utterances on out_q."""
        segmenters: dict[str, Segmenter] = {}
        while not stop.is_set():
            try:
                chunk = audio_q.get(timeout=0.2)
            except queue.Empty:
                continue
            done = segmenters.setdefault(chunk.source, Segmenter()).feed(chunk)
            if done:
                start, end, audio = done
                text, language = self.transcribe(audio)
                if text:
                    out_q.put(Utterance(chunk.source, start, end, text, language))
