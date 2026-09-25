"""Let Claude follow a meeting from the transcript.

    python -m app.follow status            latest meeting: folder, live/ended, sentence count
    python -m app.follow new               sentences since the last read
    python -m app.follow watch [--every N] print new sentences in batches every N seconds
                                           (default 20) until the meeting ends

All commands work on the newest meeting, or pass --session <folder>. `new`
and `watch` share one read position, stored as .cursor in the meeting folder,
so nothing is shown twice.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from app.session import SESSIONS_DIR

SPEAKERS = {"them": "THEM", "me": "ME"}


def latest_session(root: Path = SESSIONS_DIR) -> Path | None:
    folders = [p for p in root.glob("*") if (p / "session.json").exists()] if root.exists() else []
    return max(folders, key=lambda p: _meta(p).get("started", ""), default=None)


def _meta(folder: Path) -> dict:
    try:
        return json.loads((folder / "session.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _format(record: dict) -> str:
    speaker = SPEAKERS.get(record.get("speaker"), record.get("speaker", "?"))
    line = f"[{record.get('time')}] {speaker} ({record.get('language')}): {record.get('text')}"
    if record.get("translation"):
        line += f"\n    -> {record['translation']}"
    return line


def read_new(folder: Path) -> list[str]:
    """Sentences added since the last read; moves the read position forward."""
    transcript, cursor = folder / "transcript.jsonl", folder / ".cursor"
    if not transcript.exists():
        return []
    offset = int(cursor.read_text()) if cursor.exists() else 0
    with transcript.open("rb") as f:
        f.seek(offset)
        data = f.read()
    # Only consume complete lines; a line being written right now waits for the next read.
    end = data.rfind(b"\n") + 1
    if not end:
        return []
    cursor.write_text(str(offset + end))
    lines = []
    for raw in data[:end].decode("utf-8").splitlines():
        try:
            lines.append(_format(json.loads(raw)))
        except ValueError:
            continue
    return lines


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="python -m app.follow")
    parser.add_argument("command", choices=["status", "new", "watch"])
    parser.add_argument("--session", type=Path, help="meeting folder (default: newest)")
    parser.add_argument("--every", type=float, default=20, help="seconds between batches for watch")
    args = parser.parse_args()

    folder = args.session or latest_session()
    if not folder:
        print("no meetings yet")
        return

    if args.command == "status":
        meta = _meta(folder)
        count = sum(1 for _ in (folder / "transcript.jsonl").open(encoding="utf-8")) \
            if (folder / "transcript.jsonl").exists() else 0
        print(f"folder: {folder}")
        print(f"status: {meta.get('status')}  started: {meta.get('started')}  ended: {meta.get('ended')}")
        if meta.get("end_reason"):
            print(f"end reason: {meta['end_reason']}")
        print(f"sentences: {count}  languages: {meta.get('languages')}  subtitles: {meta.get('subtitle_language')}")
    elif args.command == "new":
        print("\n".join(read_new(folder)) or "(nothing new)")
    else:
        print(f"following {folder}", flush=True)
        while True:
            lines = read_new(folder)
            if lines:
                print("\n".join(lines), flush=True)
            meta = _meta(folder)
            if meta.get("status") == "ended":
                print(f"MEETING ENDED: {meta.get('end_reason')}", flush=True)
                return
            time.sleep(args.every)


if __name__ == "__main__":
    main()
