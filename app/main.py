"""Run a meeting: capture, transcribe, translate, show subtitles, save the session.

    python -m app.main

The meeting ends when the subtitle window is closed, or after `idle_minutes`
without speech. Progress lines are printed to stdout so Claude can follow along.
"""

import queue
import threading

from PySide6.QtCore import QTimer

from app.audio import AudioCapture
from app.config import ROOT, load_config
from app.overlay import Overlay
from app.session import Session
from app.transcribe import Transcriber
from app.translate import Translator


def log(message: str):
    print(message, flush=True)


def main():
    config = load_config()
    overlay = Overlay(state_path=ROOT / "overlay_state.json")
    session = Session(info={"source_language": config.source_language, "target_language": config.target_language})
    log(f"session: {session.path}")

    stop = threading.Event()
    state = {"end_reason": "window closed", "capture": None}

    def pipeline():
        overlay.set_status("Loading speech model…")
        try:
            transcriber = Transcriber(config.model, config.source_language)
        except Exception as error:
            overlay.set_status(f"Could not load the speech model: {error}")
            log(f"error: speech model failed to load: {error}")
            return
        log(f"model: {transcriber.description}")

        audio_q, text_q = queue.Queue(), queue.Queue()
        capture = AudioCapture(audio_q, capture_mic=config.capture_mic)
        try:
            devices = capture.start()
        except Exception as error:
            overlay.set_status(f"Could not open the audio devices: {error}")
            log(f"error: audio capture failed: {error}")
            return
        state["capture"] = capture
        session.update(model=transcriber.description, devices=devices)
        log(f"devices: {devices}")
        overlay.set_status("Listening…")
        log("listening")

        threading.Thread(target=transcriber.run, args=(audio_q, text_q, stop), daemon=True).start()
        translator = Translator(config.target_language)
        while not stop.is_set():
            try:
                utterance = text_q.get(timeout=0.2)
            except queue.Empty:
                continue
            translation = translator.translate(utterance.text, utterance.language)
            session.add(utterance.source, utterance.start, utterance.text, translation, utterance.language)
            overlay.push(utterance.source, utterance.text, translation)

    threading.Thread(target=pipeline, daemon=True).start()

    def check_idle():
        if session.idle_seconds() > config.idle_minutes * 60:
            state["end_reason"] = f"no speech for {config.idle_minutes} minutes"
            overlay.stop()

    idle_timer = QTimer()
    idle_timer.timeout.connect(check_idle)
    idle_timer.start(30_000)

    overlay.run()

    stop.set()
    if state["capture"]:
        state["capture"].stop()
    session.close(state["end_reason"])
    log(f"ended: {state['end_reason']}")


if __name__ == "__main__":
    main()
