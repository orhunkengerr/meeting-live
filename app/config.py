"""Settings with sensible defaults.

config.json only needs the keys you want to change; anything missing, or the
whole file missing, falls back to the defaults below.
"""

import ctypes
import json
import locale
from dataclasses import dataclass, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"


@dataclass
class Config:
    source_language: str = "auto"  # language spoken in the meeting, e.g. "en"; "auto" detects it
    target_language: str = "auto"  # language of the subtitles; "auto" uses your Windows display language
    model: str = "auto"            # Whisper model, "auto" picks one for your GPU
    capture_mic: bool = True       # also transcribe your own voice
    idle_minutes: int = 20         # end the meeting after this long without speech


def system_language() -> str:
    """Two-letter code of the Windows display language, e.g. "tr"."""
    try:
        lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return locale.windows_locale.get(lcid, "en_US").split("_")[0]
    except (AttributeError, OSError):
        return "en"


def load_config(path: Path = CONFIG_PATH) -> Config:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except json.JSONDecodeError as error:
        raise SystemExit(f"{path.name} is not valid JSON: {error}")
    known = {f.name for f in fields(Config)}
    config = Config(**{key: value for key, value in data.items() if key in known})
    if config.target_language == "auto":
        config.target_language = system_language()
    return config
