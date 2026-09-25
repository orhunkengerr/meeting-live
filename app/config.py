"""Settings with sensible defaults.

config.json only needs the keys you want to change; anything missing, or the
whole file missing, falls back to the defaults below. The two audio channels
are set up separately, since you and the other side often speak different
languages.
"""

import ctypes
import json
import locale
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Settings and meetings live outside the code, so updating the app (or the
# Claude Code plugin, whose folder changes with every version) never touches them.
DATA_DIR = Path(os.environ.get("MEETING_LIVE_HOME") or Path.home() / "meeting-live")
CONFIG_PATH = DATA_DIR / "config.json"


@dataclass
class Channel:
    enabled: bool = True
    device: str = "default"  # a device name from app.audio.list_devices(), or "default"
    language: str = "auto"   # e.g. "en"; "auto" detects it and locks after a few sentences


@dataclass
class Config:
    meeting_audio: Channel = field(default_factory=Channel)  # what comes out of your speakers
    microphone: Channel = field(default_factory=Channel)     # your own voice
    subtitle_language: str = "auto"  # "auto" uses your Windows display language
    model: str = "auto"              # Whisper model, "auto" picks one for your GPU
    idle_minutes: int = 20           # end the meeting after this long without speech
    your_name: str = ""              # how people address you, so Claude notices questions aimed at you

    def target_language(self) -> str:
        return system_language() if self.subtitle_language == "auto" else self.subtitle_language


def system_language() -> str:
    """Two-letter code of the Windows display language, e.g. "tr"."""
    try:
        lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return locale.windows_locale.get(lcid, "en_US").split("_")[0]
    except (AttributeError, OSError):
        return "en"


def _pick(cls, data) -> dict:
    known = {f.name for f in fields(cls)}
    return {key: value for key, value in (data or {}).items() if key in known}


def load_config(path: Path = CONFIG_PATH) -> Config:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        data = {}
    except json.JSONDecodeError as error:
        raise SystemExit(f"{path.name} is not valid JSON: {error}")
    top = _pick(Config, data)
    top["meeting_audio"] = Channel(**_pick(Channel, data.get("meeting_audio")))
    top["microphone"] = Channel(**_pick(Channel, data.get("microphone")))
    return Config(**top)


def save_config(config: Config, path: Path = CONFIG_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
