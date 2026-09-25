"""One folder per meeting.

    sessions/2026-09-25_1430/
      session.json      start and end time, status, why it ended, topic
      transcript.jsonl  one line per sentence: time, speaker, original, translation
      notes.md          live notes (written by Claude)
      minutes.md        final minutes (written by Claude)

After the meeting the folder is renamed after its topic:

    python -m app.session rename sessions/2026-09-25_1430 "Weekly SEO sync"
    -> sessions/2026-09-25_1430_weekly-seo-sync
"""

import json
import re
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

SESSIONS_DIR = Path(__file__).resolve().parent.parent / "sessions"
TURKISH = str.maketrans("ıİşŞğĞçÇöÖüÜ", "iIsSgGcCoOuU")


class Session:
    def __init__(self, root: Path = SESSIONS_DIR, info: dict | None = None):
        now = datetime.now()
        stamp = now.strftime("%Y-%m-%d_%H%M")
        path, n = root / stamp, 2
        while path.exists():
            path, n = root / f"{stamp}-{n}", n + 1
        path.mkdir(parents=True)

        self.path = path
        self.transcript = path / "transcript.jsonl"
        self.last_activity = time.time()
        self._meta = {"id": path.name, "started": now.isoformat(timespec="seconds"), "ended": None,
                      "status": "live", "end_reason": None, "topic": None, **(info or {})}
        self._write_meta()
        self._file = self.transcript.open("a", encoding="utf-8")

    def update(self, **info):
        """Add details to session.json, e.g. the model and devices in use."""
        self._meta.update(info)
        self._write_meta()

    def add(self, source: str, start: float, original: str, translation: str | None, language: str | None = None):
        """Append one sentence. source is "them" or "me", start is a time.time() value."""
        if self._file.closed:
            return
        record = {
            "time": datetime.fromtimestamp(start).strftime("%H:%M:%S"),
            "speaker": source,
            "language": language,
            "text": original,
            "translation": translation,
        }
        self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._file.flush()
        self.last_activity = time.time()

    def idle_seconds(self) -> float:
        return time.time() - self.last_activity

    def close(self, reason: str = "window closed"):
        """Mark the meeting as ended. Safe to call more than once."""
        if self._file.closed:
            return
        self._file.close()
        self._meta.update(ended=datetime.now().isoformat(timespec="seconds"), status="ended", end_reason=reason)
        self._write_meta()

    def _write_meta(self):
        (self.path / "session.json").write_text(json.dumps(self._meta, indent=2, ensure_ascii=False), encoding="utf-8")


def slugify(text: str, max_length: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text.translate(TURKISH)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:max_length].rstrip("-")


def rename_session(path: Path, topic: str) -> Path:
    """Rename a finished meeting's folder to <id>_<topic-slug> and store the topic."""
    meta_path = path / "session.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("status") != "ended":
        raise ValueError("the meeting is still live; rename it after it ends")
    meta["topic"] = topic
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    slug = slugify(topic)
    target = path.with_name(f"{meta['id']}_{slug}" if slug else meta["id"])
    if target != path:
        path.rename(target)
    return target


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "rename":
        print(rename_session(Path(sys.argv[2]), sys.argv[3]))
    else:
        print('usage: python -m app.session rename <session folder> "<topic>"')
        sys.exit(2)
