"""Run a meeting: capture, transcribe, translate, show subtitles, save the session.

    python -m app.main

On the very first run (no config.json yet) the settings page opens before
anything is captured. Settings can be changed mid-meeting from the gear
button; capture restarts with them, the speech model stays loaded.

The meeting ends when the subtitle window is closed, or after `idle_minutes`
without speech. Progress lines are printed to stdout so Claude can follow along.
"""

import queue
import threading

from PySide6.QtCore import QTimer

from app.audio import AudioCapture, list_devices
from app.config import CONFIG_PATH, DATA_DIR, Config, load_config, save_config
from app.overlay import Overlay
from app.session import Session
from app.settings_view import SettingsView
from app.transcribe import Transcriber
from app.translate import Translator


def log(message: str):
    print(message, flush=True)


class Meeting:
    """Owns the capture → transcribe → translate → show/save pipeline and can restart it."""

    def __init__(self, overlay: Overlay, session: Session):
        self.overlay = overlay
        self.session = session
        self.transcriber = None
        self._capture = None
        self._run_stop = None
        self._lock = threading.Lock()

    def start(self, config: Config):
        """(Re)start capturing with these settings. Returns immediately."""
        threading.Thread(target=self._start, args=(config,), daemon=True).start()

    def stop(self):
        with self._lock:
            self._stop_run()

    def _stop_run(self):
        if self._run_stop:
            self._run_stop.set()
            self._run_stop = None
        if self._capture:
            self._capture.stop()
            self._capture = None

    def _start(self, config: Config):
        with self._lock:
            self._stop_run()
            channels = {"them": config.meeting_audio, "me": config.microphone}
            enabled = {source: channel for source, channel in channels.items() if channel.enabled}
            if not enabled:
                self.overlay.set_status("Both audio channels are off. Turn one on in the settings.")
                log("error: no audio channel enabled")
                return

            if self.transcriber is None:
                self.overlay.set_status("Loading speech model…")
                try:
                    self.transcriber = Transcriber(config.model)
                except Exception as error:
                    self.overlay.set_status(f"Could not load the speech model: {error}")
                    log(f"error: speech model failed to load: {error}")
                    return
                log(f"model: {self.transcriber.description}")
            languages = {source: channel.language for source, channel in enabled.items()}
            self.transcriber.set_languages(languages)

            audio_q, text_q = queue.Queue(), queue.Queue()
            capture = AudioCapture(audio_q, {source: channel.device for source, channel in enabled.items()})
            try:
                devices = capture.start()
            except Exception as error:
                self.overlay.set_status(f"Could not open the audio devices: {error}")
                log(f"error: audio capture failed: {error}")
                return
            self._capture = capture
            stop = self._run_stop = threading.Event()

            target = config.target_language()
            self.session.update(model=self.transcriber.description, devices=devices,
                                languages=languages, subtitle_language=target)
            log(f"devices: {devices}")
            log(f"languages: {languages}, subtitles: {target}")
            self.overlay.set_status("Listening…")
            log("listening")

            threading.Thread(target=self.transcriber.run, args=(audio_q, text_q, stop), daemon=True).start()
            threading.Thread(target=self._deliver, args=(text_q, Translator(target), stop), daemon=True).start()

    def _deliver(self, text_q: queue.Queue, translator: Translator, stop: threading.Event):
        while not stop.is_set():
            try:
                utterance = text_q.get(timeout=0.2)
            except queue.Empty:
                continue
            translation = translator.translate(utterance.text, utterance.language)
            self.session.add(utterance.source, utterance.start, utterance.text, translation, utterance.language)
            self.overlay.push(utterance.source, utterance.text, translation)


def main():
    first_run = not CONFIG_PATH.exists()
    config = load_config()
    overlay = Overlay(state_path=DATA_DIR / "overlay_state.json")
    session = Session()
    meeting = Meeting(overlay, session)
    log(f"session: {session.path}")
    state = {"end_reason": "window closed", "started": False}

    def open_settings():
        view = SettingsView(load_config(), list_devices())

        def saved(new_config: Config):
            save_config(new_config)
            log("settings saved")
            overlay.show_subtitles()
            meeting.start(new_config)
            state["started"] = True

        def cancelled():
            overlay.show_subtitles()
            if not state["started"]:
                meeting.start(load_config())
                state["started"] = True

        view.saved.connect(saved)
        view.cancelled.connect(cancelled)
        overlay.show_settings(view)

    overlay.settings_requested.connect(open_settings)
    if first_run:
        overlay.set_status("Choose your audio settings to start.")
        QTimer.singleShot(0, open_settings)
    else:
        meeting.start(config)
        state["started"] = True

    def check_idle():
        if session.idle_seconds() > config.idle_minutes * 60:
            state["end_reason"] = f"no speech for {config.idle_minutes} minutes"
            overlay.stop()

    idle_timer = QTimer()
    idle_timer.timeout.connect(check_idle)
    idle_timer.start(30_000)

    overlay.run()

    meeting.stop()
    session.close(state["end_reason"])
    log(f"ended: {state['end_reason']}")


if __name__ == "__main__":
    main()
