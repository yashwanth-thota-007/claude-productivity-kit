#!/usr/bin/env python3
"""
Voice input — macOS menu bar app.
Double-tap Ctrl to start/stop recording. Transcribes locally via Whisper, pastes into active window.

Auto-starts on login via LaunchAgent: com.claude.voice-menubar
To enable:  launchctl load ~/Library/LaunchAgents/com.claude.voice-menubar.plist
To disable: launchctl unload ~/Library/LaunchAgents/com.claude.voice-menubar.plist

Transcript log: ~/.claude/voice-transcripts.jsonl (rolling 100 entries)
"""
import sys, argparse, threading, time, json
from datetime import datetime
from collections import deque
from pathlib import Path
import numpy as np
import sounddevice as sd
import whisper, pyperclip, rumps
from pynput import keyboard
from AppKit import NSSound
from Quartz import (
    CGEventCreateKeyboardEvent, CGEventPost,
    kCGHIDEventTap, CGEventSetFlags, kCGEventFlagMaskCommand,
)

SAMPLE_RATE       = 16000
DOUBLE_TAP_WINDOW = 0.4
MODELS            = ["tiny", "base", "small", "medium", "large"]
DEFAULT_MODEL     = "small"
RECENT_COUNT      = 5     # shown in menu
LOG_MAX           = 100   # entries kept in transcript log

ICON_IDLE       = "🎙"
ICON_RECORDING  = "🔴"
ICON_PROCESSING = "⏳"
ICON_LOADING    = "⌛"

SOUND_START = "Ping"
SOUND_STOP  = "Pop"

LOG_PATH = Path.home() / ".claude" / "voice-transcripts.jsonl"


def play_sound(name: str):
    s = NSSound.soundNamed_(name)
    if s:
        s.play()


def load_log() -> deque:
    """Load existing transcript log into a deque capped at LOG_MAX."""
    entries = deque(maxlen=LOG_MAX)
    if LOG_PATH.exists():
        for line in LOG_PATH.read_text().strip().splitlines():
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
    return entries


def save_log(entries: deque):
    """Rewrite the log file with current entries."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text("\n".join(json.dumps(e) for e in entries) + "\n")


def append_transcript(entries: deque, text: str, model: str):
    """Add a new entry and persist. Deque handles the 100-entry cap."""
    entries.append({
        "ts": datetime.now().isoformat(timespec="seconds"),
        "model": model,
        "text": text,
    })
    save_log(entries)


class VoiceApp(rumps.App):
    def __init__(self, model_name: str):
        super().__init__(ICON_LOADING, quit_button="Quit")
        self.model_name   = model_name
        self.model        = None
        self.recording    = False
        self.audio_frames = []
        self.stream       = None
        self.last_ctrl    = 0.0
        self._model_lock  = threading.Lock()
        self._log         = load_log()

        # Status
        self.status_item = rumps.MenuItem("Status: Loading model...")

        # Recent transcripts submenu (last 5)
        self.recent_menu = rumps.MenuItem("Recent Transcripts")
        self.recent_items = []
        for i in range(RECENT_COUNT):
            item = rumps.MenuItem(f"  —", callback=self._copy_recent)
            self.recent_items.append(item)
            self.recent_menu.add(item)
        self.recent_menu.add(None)
        self.recent_menu.add(rumps.MenuItem("Open Log File", callback=self._open_log))
        self._refresh_recent_menu()

        # Model switcher
        self.model_items = {}
        model_menu = rumps.MenuItem("Model")
        for m in MODELS:
            item = rumps.MenuItem(m, callback=self._switch_model)
            item.state = (m == model_name)
            model_menu.add(item)
            self.model_items[m] = item

        self.menu = [
            self.status_item,
            None,
            self.recent_menu,
            None,
            model_menu,
            None,
        ]

        threading.Thread(target=self._load_model, args=(model_name,), daemon=True).start()
        self.listener = keyboard.Listener(on_press=self._on_press, on_release=lambda k: None)
        self.listener.start()

    # ── Recent transcripts ───────────────────────────────────────────────────

    def _refresh_recent_menu(self):
        """Update the last-5 menu items from the log."""
        recent = list(self._log)[-RECENT_COUNT:]
        recent.reverse()  # newest first
        for i, item in enumerate(self.recent_items):
            if i < len(recent):
                entry = recent[i]
                ts    = entry["ts"][11:16]  # HH:MM
                text  = entry["text"]
                label = f"  [{ts}] {text[:50]}{'…' if len(text) > 50 else ''}"
                item.title = label
                item._full_text = entry["text"]  # stash for copy-on-click
            else:
                item.title = "  —"
                item._full_text = ""

    def _copy_recent(self, sender):
        text = getattr(sender, "_full_text", "")
        if text:
            pyperclip.copy(text)
            self.status_item.title = "Status: Copied to clipboard"
            threading.Timer(2.0, lambda: self._reset_idle("Ready")).start()

    def _open_log(self, _):
        import subprocess
        subprocess.Popen(["open", str(LOG_PATH)])

    # ── Model loading ────────────────────────────────────────────────────────

    def _load_model(self, name: str):
        self.title = ICON_LOADING
        self.status_item.title = f"Status: Loading {name}..."
        with self._model_lock:
            self.model = whisper.load_model(name)
            self.model_name = name
        self.status_item.title = "Status: Ready"
        self.title = ICON_IDLE

    def _switch_model(self, sender):
        if sender.title == self.model_name and self.model is not None:
            return
        for m, item in self.model_items.items():
            item.state = (m == sender.title)
        threading.Thread(target=self._load_model, args=(sender.title,), daemon=True).start()

    # ── Hotkey ───────────────────────────────────────────────────────────────

    def _on_press(self, key):
        if key not in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            return
        now = time.time()
        is_double = (now - self.last_ctrl) < DOUBLE_TAP_WINDOW
        self.last_ctrl = now
        if not is_double:
            return
        if not self.recording:
            self._start_recording()
        else:
            self._stop_recording()

    # ── Recording ────────────────────────────────────────────────────────────

    def _audio_callback(self, indata, frame_count, time_info, status):
        if self.recording:
            self.audio_frames.append(indata.copy())

    def _start_recording(self):
        if self.model is None:
            rumps.notification("Voice Input", "", "Model still loading, please wait.")
            return
        self.recording    = True
        self.audio_frames = []
        self.title        = ICON_RECORDING
        self.status_item.title = "Status: Recording..."
        play_sound(SOUND_START)
        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1,
            dtype="float32", callback=self._audio_callback,
        )
        self.stream.start()

    def _stop_recording(self):
        self.recording = False
        play_sound(SOUND_STOP)
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        self.title = ICON_PROCESSING
        self.status_item.title = "Status: Transcribing..."
        threading.Thread(target=self._transcribe_and_paste, daemon=True).start()

    # ── Transcription + paste ────────────────────────────────────────────────

    def _transcribe_and_paste(self):
        if not self.audio_frames:
            self._reset_idle("No audio captured.")
            return
        audio = np.concatenate(self.audio_frames, axis=0).flatten()
        self.audio_frames = []
        if len(audio) < SAMPLE_RATE:
            self._reset_idle("Too short.")
            return

        with self._model_lock:
            result = self.model.transcribe(audio, fp16=False)

        text = result["text"].strip()
        if not text:
            self._reset_idle("No speech detected.")
            return

        # Log + update menu
        append_transcript(self._log, text, self.model_name)
        self._refresh_recent_menu()

        # Paste into active window
        pyperclip.copy(text)
        time.sleep(0.1)
        for down in (True, False):
            evt = CGEventCreateKeyboardEvent(None, 0x09, down)
            CGEventSetFlags(evt, kCGEventFlagMaskCommand)
            CGEventPost(kCGHIDEventTap, evt)

        self._reset_idle("Ready")

    def _reset_idle(self, status: str):
        self.title = ICON_IDLE
        self.status_item.title = f"Status: {status}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL, choices=MODELS)
    args = parser.parse_args()
    VoiceApp(args.model).run()


if __name__ == "__main__":
    main()
