# meeting-live

Live subtitles for any meeting on your screen, with Claude following the meeting for you.

meeting-live listens to your meeting audio and your microphone, transcribes both locally with Whisper, translates them into your language and shows them in a small window that stays on top and is hidden from screen sharing. As a Claude Code plugin, Claude reads along: it keeps running notes, tells you the moment a question is aimed at you and suggests what to answer, and writes the minutes when the meeting ends.

Works with Zoom, Google Meet, Teams, or anything else that plays sound. Windows only for now.

## What it does

- **Subtitles for both sides.** The other side (your speakers) and you (your microphone) are captured separately, each with its own device and language.
- **Local speech recognition.** Whisper runs on your machine; the model is picked for your GPU and never below `medium`. No API keys, no account.
- **Translation into your language.** Subtitles follow your Windows display language unless you choose another. A sentence already in your language is not translated.
- **A window that stays out of the way.** Always on top, see-through, movable and resizable, scrollable history, and invisible in screen shares and recordings.
- **Claude in the meeting.** Running notes, questions aimed at you with replies you can say, action items, and minutes at the end.
- **One folder per meeting.** Transcript, notes and minutes are saved together and the folder is named after the topic.

## Install as a Claude Code plugin

Needs Windows 10 (2004 or later) or 11, Python 3.10+ and [Claude Code](https://claude.com/claude-code). An NVIDIA GPU makes it much faster but is not required.

In Claude Code:

```
/plugin marketplace add orhunkengerr/meeting-live
/plugin install meeting-live@meeting-live
```

Then start a new Claude Code session.

## Use

**`/meeting-live`** (full name `/meeting-live:start`) when a meeting begins.

The first time, Claude installs the app's environment and asks five questions: the meeting's language, the language you speak, the subtitle language, whether to transcribe your microphone, and the name people call you. Then the subtitle window opens and Claude starts following.

During the meeting Claude stays quiet unless something needs you: a question aimed at you, a task given to you, a decision that affects you. Close the subtitle window to end the meeting and keep the Claude session open a few seconds for the minutes.

**`/meeting-live:minutes`** writes minutes later: for meetings that ended without them (for example when Claude was closed too early), or again for a meeting you name.

## How it works

```
speakers ──┐                                      ┌─> subtitle window
           ├─> Silero VAD ─> Whisper ─> translate ┤
microphone ┘   (speech?)     (local)   (Google)   └─> transcript.jsonl ─> Claude: notes, replies, minutes
```

1. WASAPI captures the speaker output (loopback) and the microphone as two channels.
2. Silero VAD finds where speech starts and stops; a sentence is cut at the pause after it.
3. faster-whisper transcribes the sentence. With the language on detect, each channel locks to the language it hears in its first few confident sentences.
4. The sentence is translated, shown in the window and appended to the meeting's transcript.
5. Claude reads new lines every 20 seconds through `python -m app.follow watch`.

| Your machine | Whisper model |
|---|---|
| NVIDIA GPU with 4 GB or more | large-v3-turbo |
| Smaller NVIDIA GPU | medium |
| No NVIDIA GPU | medium on the CPU (subtitles arrive a few seconds late) |

## Run without Claude

```
python setup_env.py
%USERPROFILE%\meeting-live\venv\Scripts\python.exe -m app.main
```

The first run opens the settings page. You get subtitles and saved transcripts; notes, replies and minutes need Claude.

## Settings and files

Everything lives in `%USERPROFILE%\meeting-live`, apart from the code, so updates never touch it:

```
config.json          settings (also editable from the gear button in the window)
overlay_state.json   window position, size and text size
venv/                the app's Python environment
sessions/
  2026-09-25_1430_weekly-seo-sync/
    session.json       times, languages, devices, model
    transcript.jsonl   every sentence: time, speaker, language, text, translation
    notes.md           Claude's running notes
    minutes.md         Claude's minutes
```

`config.json`:

| Key | Default | Meaning |
|---|---|---|
| `meeting_audio` | on, default device, detect | the other side: `enabled`, `device`, `language` |
| `microphone` | on, default device, detect | you: `enabled`, `device`, `language` |
| `subtitle_language` | `auto` | `auto` uses your Windows display language |
| `model` | `auto` | or a Whisper model name such as `medium` |
| `idle_minutes` | `20` | the meeting ends after this long without speech |
| `your_name` | empty | lets Claude notice questions aimed at you |

## Privacy

Audio never leaves your computer and transcripts are only stored locally. Two things do go out: each sentence is sent to Google Translate for its translation, and when you use the plugin, Claude reads the transcript like any other file you give it.

## Limits

- Windows only for now.
- Speakers on the other side are not told apart yet; everyone there is "them".
- Whisper still mishears names and very short words, and sometimes writes a stock phrase over silence.

## License

MIT
