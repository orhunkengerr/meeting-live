# meeting-live

Live meeting subtitles on your screen, with Claude following the meeting for you.

The app captures your meeting audio (the other side and your microphone), transcribes it locally with Whisper, translates it into your language and shows it in a small always-on-top window that stays hidden from screen sharing. Every sentence is saved to a per-meeting folder. Used as a Claude Code skill, Claude follows the transcript live: it keeps running notes, flags questions aimed at you, suggests replies, and writes the minutes when the meeting ends.

Status: work in progress. Windows only for now.

- Local speech recognition, no API keys. The Whisper model is chosen from your GPU's memory.
- Meeting language is detected automatically; subtitles follow your Windows display language.
- Recordings never leave your machine.

MIT License
