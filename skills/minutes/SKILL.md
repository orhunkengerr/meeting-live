---
name: minutes
description: Write or rewrite the minutes of a meeting recorded by meeting-live, and name its folder after the topic. Without an argument, handles meetings that ended without minutes.
argument-hint: "[meeting folder or topic words]"
disable-model-invocation: true
---

# Meeting minutes

Write the minutes of a meeting recorded by meeting-live. Talk to the user in the language they use with you.

App code: `${CLAUDE_PLUGIN_ROOT}`. The commands below need only the standard library, so plain `python` (3.10+) works; run them from `${CLAUDE_PLUGIN_ROOT}`.

## Pick the meeting

- Argument given (`$ARGUMENTS`): a folder path, or words to match against folder names and topics in `python -m app.follow list`.
- No argument: `python -m app.follow pending`. One meeting: use it. Several: write them all, oldest first, unless the user says otherwise. None: show the last few from `list` and ask which one to redo.
- A meeting whose status is still `live` is in progress; say so and stop.

## Write the minutes

1. Read the whole transcript: `python -m app.follow all --session "<folder>"`. Also read `notes.md` in the folder if it exists, and `session.json` for times and languages.
   Lines look like `[12:01:03] THEM (en): text` with `-> translation` under it. THEM is the other side, ME is the user (their name is `your_name` in `~/meeting-live/config.json`). The transcript has recognition mistakes: read through them by context and never quote gibberish.
2. Write `minutes.md` in the folder, in the user's language (overwrite it when rewriting):
   - Title, date, start and end time, participants (names heard)
   - Summary (3–5 sentences)
   - Decisions
   - Action items as a checklist: owner, task, due date
   - Open questions and follow-ups
   If the transcript is too short or empty to say anything real, write that plainly instead of inventing content.
3. Pick a short topic (3–5 words, in the meeting's language) and rename the folder:
   `python -m app.session rename "<folder>" "<topic>"`
   It prints the new path. Skip renaming if the folder already has the topic you would give it.
4. Tell the user: the summary in 2–3 lines, their own action items, and the path to `minutes.md`.
