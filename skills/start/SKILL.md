---
name: start
description: Start live meeting subtitles and follow the meeting for the user. Sets up the app on first use, keeps running notes, flags questions aimed at the user with a suggested reply, and writes the minutes when the meeting ends.
disable-model-invocation: true
---

# Meeting Live

You run the meeting-live app (local Whisper subtitles in an always-on-top window) and follow the meeting through its transcript. The subtitles are instant; your job is the thinking a step behind them.

Talk to the user in the language they use with you. Keep chat messages short: they are in a meeting.

App code: `${CLAUDE_PLUGIN_ROOT}`
User data: `~/meeting-live/` (settings in `config.json`, meetings in `sessions/`)

## 0. Meetings left without minutes

Minutes are written by Claude after the meeting, so they are missing when this session was closed too early. Run `python -m app.follow pending` from `${CLAUDE_PLUGIN_ROOT}` (standard library only, no setup needed). If it lists meetings, ask the user in one line whether to write their minutes now. On yes, follow `${CLAUDE_PLUGIN_ROOT}/skills/minutes/SKILL.md` for each of them before starting a new meeting (or right after, if they want to start now).

## 1. Set up (every time, it is fast when nothing changed)

1. Check Python: `python --version`. It needs 3.10 or newer. If Python is missing, tell the user to install it (`winget install Python.Python.3.12`) and stop.
2. Run `python "${CLAUDE_PLUGIN_ROOT}/setup_env.py"` with `run_in_background` (the first run downloads a few GB and takes minutes). Tell the user it is installing. The last line it prints is the environment's Python; call it `$PY` below.
3. If `~/meeting-live/config.json` does not exist, ask the user in ONE message:
   - What language is the meeting in? (or "detect")
   - What language will you speak? (or "detect")
   - What language do you want subtitles in? (default: their Windows language)
   - Should your microphone be transcribed too? (default yes)
   - What name do people call you in meetings?

   Then write `~/meeting-live/config.json` (two-letter language codes, `"auto"` for detect):
   ```json
   {
     "meeting_audio": {"enabled": true, "device": "default", "language": "en"},
     "microphone": {"enabled": true, "device": "default", "language": "tr"},
     "subtitle_language": "auto",
     "model": "auto",
     "idle_minutes": 20,
     "your_name": "Orhun"
   }
   ```
   If the config exists, do not ask again; read `your_name` from it.

## 2. Start the meeting

1. From `${CLAUDE_PLUGIN_ROOT}`, run `"$PY" -u -m app.main` with `run_in_background`. The subtitle window opens; the first start loads the speech model (seconds on a GPU, the first download takes longer).
2. Watch its output for `session: <folder>`, `listening` and `error:` lines. On an error, tell the user what it says. Devices and languages can also be changed from the gear button in the window.
3. Tell the user in one line that it is listening, that closing the window (x) ends the meeting, and to keep this Claude session open for a few seconds after that so you can write the minutes (`/meeting-live:minutes` can write them later too).
4. Start following with the Monitor tool, from `${CLAUDE_PLUGIN_ROOT}`:
   `"$PY" -m app.follow watch --every 20` with `timeout_ms` 1800000. When the monitor expires and the meeting is still live, start it again.

## 3. During the meeting

Each batch of lines looks like `[12:01:03] THEM (en): text` with `-> translation` under it. THEM is the other side, ME is the user.

On every batch, update `notes.md` in the session folder (overwrite it, keep it tight):
- **Context**: what the meeting is about, who is there (names heard)
- **Discussed so far**: short bullets
- **Decisions**
- **Action items**: who, what, by when
- **Open questions**

Speak up in chat only when it helps right now:
- **A question or request aimed at the user** (their name, "you", or a clear pause for their answer): say what was asked in the user's language, then give 1–2 short replies they can say, in the meeting's language. This is the most important thing you do; do it at once.
- **Something assigned to the user**, a deadline, or a decision that affects them: one line.
- Otherwise stay quiet. Never repeat the transcript back.

Transcripts contain recognition mistakes; read through them by context. If a whole batch is gibberish or in an unexpected language, the language setting is probably wrong: tell the user and suggest fixing it with the gear button.

## 4. When the meeting ends

The monitor prints `MEETING ENDED: <reason>` (the window was closed or it was silent for `idle_minutes`).

Read `${CLAUDE_PLUGIN_ROOT}/skills/minutes/SKILL.md` and follow it for this meeting's folder. You already have the transcript and notes in context, so only run `"$PY" -m app.follow new` for any last lines instead of reading everything again.
