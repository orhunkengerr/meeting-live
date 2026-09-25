"""Turn the audio stream into sentences with Whisper.

Each source ("them", "me") gets its own segmenter that cuts the stream at
pauses. Finished segments are transcribed with faster-whisper. With the model
set to "auto", its size is picked from the GPU's memory.
"""

import os
import queue
import subprocess
import threading
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from pathlib import Path


def _add_nvidia_dll_dirs():
    """pip's NVIDIA wheels put their DLLs in site-packages/nvidia/*/bin, which Windows does not search."""
    try:
        import nvidia
    except ImportError:
        return
    for base in nvidia.__path__:
        for bin_dir in Path(base).glob("*/bin"):
            os.add_dll_directory(str(bin_dir))
            os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"


_add_nvidia_dll_dirs()

import numpy as np  # noqa: E402
from faster_whisper import WhisperModel  # noqa: E402
from faster_whisper.vad import get_vad_model  # noqa: E402

from app.audio import TARGET_RATE, AudioChunk  # noqa: E402

# (minimum VRAM in MB, model). The first match wins. Nothing below medium:
# smaller models make up sentences from background noise.
GPU_TIERS = [(4000, "large-v3-turbo"), (0, "medium")]
CPU_MODEL = "medium"

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


class SpeechDetector:
    """Tells speech from music, noise and silence with Silero VAD (bundled with faster-whisper).

    Loudness alone is not enough: during a long talk with no pauses, a loudness
    threshold slowly learns the voice as "background" and stops hearing it.
    The model looks at each new 32 ms frame with about a second of context.
    """

    FRAME = 512           # samples per VAD frame at 16 kHz
    CONTEXT_FRAMES = 30

    def __init__(self, threshold: float = 0.5):
        self.model = get_vad_model()
        self.threshold = threshold
        self.pending = np.zeros(0, dtype=np.float32)
        self.history = np.zeros(0, dtype=np.float32)
        self.last_probability = 0.0

    def is_speech(self, samples: np.ndarray) -> bool:
        self.pending = np.concatenate([self.pending, samples])
        n = len(self.pending) // self.FRAME * self.FRAME
        if n:
            new, self.pending = self.pending[:n], self.pending[n:]
            window = np.concatenate([self.history, new])
            probabilities = np.asarray(self.model(window)).reshape(-1)[-(n // self.FRAME):]
            self.history = window[-self.CONTEXT_FRAMES * self.FRAME:]
            self.last_probability = float(probabilities.max())
        return self.last_probability >= self.threshold


class Segmenter:
    """Cuts one source's audio into utterances at pauses in speech."""

    # preroll keeps the quiet start of a word ("s" in "selam") before speech is detected.
    def __init__(self, silence_ms=700, min_speech_ms=400, max_ms=15000, preroll_ms=500):
        self.silence_ms = silence_ms
        self.min_speech_ms = min_speech_ms
        self.max_ms = max_ms
        self.preroll = deque(maxlen=max(1, preroll_ms // 100))
        self.detector = SpeechDetector()
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
        speaking = self.detector.is_speech(samples)

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
    def __init__(self, model: str = "auto", languages: dict[str, str] | None = None):
        """languages maps a source ("them", "me") to a language code or "auto"."""
        name, device, compute = pick_model(model)
        try:
            self.model = self._load(name, device, compute)
        except Exception:
            # CUDA libraries missing or GPU unusable: fall back to the CPU.
            if device == "cpu":
                raise
            name, device, compute = (CPU_MODEL if model == "auto" else name), "cpu", "int8"
            self.model = self._load(name, device, compute)
        # A GPU has time to compare several guesses (better on short words); a CPU does not.
        self.beam_size = 5 if device == "cuda" else 1
        self.description = f"{name} on {device}, beam {self.beam_size}"
        self.set_languages(languages or {})

    def set_languages(self, languages: dict[str, str]):
        """Each source detects and locks its own language: you and the other side may differ."""
        self.languages = {source: None if lang == "auto" else lang for source, lang in languages.items()}
        self._votes: dict[str, Counter] = defaultdict(Counter)

    @staticmethod
    def _load(name: str, device: str, compute: str) -> WhisperModel:
        model = WhisperModel(name, device=device, compute_type=compute)
        # Warm up once so a broken GPU setup fails here, not mid-meeting.
        list(model.transcribe(np.zeros(TARGET_RATE, dtype=np.float32))[0])
        return model

    def transcribe(self, audio: np.ndarray, source: str = "them") -> tuple[str, str]:
        """Return (text, language)."""
        segments, info = self.model.transcribe(
            audio,
            language=self.languages.get(source),
            beam_size=self.beam_size,
            condition_on_previous_text=False,
        )
        text = " ".join(s.text.strip() for s in segments if s.no_speech_prob < 0.6).strip()
        if (self.languages.get(source) is None and text and len(audio) >= LOCK_MIN_SECONDS * TARGET_RATE
                and info.language_probability >= LOCK_MIN_PROBABILITY):
            votes = self._votes[source]
            votes[info.language] += 1
            language, count = votes.most_common(1)[0]
            if count >= LOCK_VOTES:
                self.languages[source] = language
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
                text, language = self.transcribe(audio, chunk.source)
                if text:
                    out_q.put(Utterance(chunk.source, start, end, text, language))
