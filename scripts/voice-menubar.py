#!/usr/bin/env python3
"""
Voice input + image paste — macOS menu bar app.
Double-tap Ctrl  → start/stop recording, transcribes via Whisper, pastes into active window.
Double-tap Option → save clipboard image to ~/.claude/paste-images/, paste @path into active window.

Auto-starts on login via LaunchAgent: com.claude.voice-menubar
To enable:  launchctl load ~/Library/LaunchAgents/com.claude.voice-menubar.plist
To disable: launchctl unload ~/Library/LaunchAgents/com.claude.voice-menubar.plist

Transcript log: ~/.claude/voice-transcripts.jsonl (rolling 100 entries)
"""
import sys, argparse, threading, time, json, subprocess, tempfile
from datetime import datetime
from collections import deque
from pathlib import Path
import numpy as np
import sounddevice as sd
import whisper, pyperclip, rumps, webrtcvad
from pynput import keyboard
from AppKit import NSSound, NSPasteboard

SAMPLE_RATE       = 16000
DOUBLE_TAP_WINDOW = 0.4
MODELS            = ["tiny", "base", "small", "medium", "large"]
DEFAULT_MODEL     = "base"
RECENT_COUNT      = 5     # shown in menu
LOG_MAX           = 100   # entries kept in transcript log
TRAILING_SILENCE  = 2.0   # seconds of silence after speech → auto-stop
VAD_AGGRESSIVENESS = 3    # 0–3; 3 = most aggressive noise filtering
VAD_FRAME_MS      = 30    # webrtcvad frame size (10/20/30 ms)
VAD_FRAME_BYTES   = int(SAMPLE_RATE * VAD_FRAME_MS / 1000) * 2  # 16-bit PCM

ICON_IDLE       = "🎙"
ICON_RECORDING  = "🔴"
ICON_PROCESSING = "⏳"
ICON_LOADING    = "⌛"

SOUND_START  = "Ping"
SOUND_STOP   = "Pop"
SOUND_IMAGE  = "Glass"
SOUND_POMO   = "Sosumi"

LOG_PATH         = Path.home() / ".claude" / "voice-transcripts.jsonl"
IMAGES_BASE      = Path.home() / ".claude" / "paste-images"
ACTIVE_SID_FILE  = Path.home() / ".claude" / "active-session-id"
POMODORO_SIGNAL  = Path.home() / ".claude" / "pomodoro-signal.json"
POMODORO_STATE   = Path.home() / ".claude" / "pomodoro-state.json"

POMO_PRESETS  = [25, 50, 90]   # minutes shown in manual menu
POMO_WARN_MIN = 5              # warning notification N minutes before end


def current_images_dir() -> Path:
    """Return paste-images/<session_id> if a session is active, else base dir."""
    if ACTIVE_SID_FILE.exists():
        sid = ACTIVE_SID_FILE.read_text().strip()
        if sid:
            return IMAGES_BASE / sid
    return IMAGES_BASE

# NSPasteboard types to try for image data
_IMG_TYPES = [
    ("public.png",          "png"),
    ("NSPasteboardTypePNG", "png"),
    ("public.tiff",         "tiff"),
    ("NSPasteboardTypeTIFF","tiff"),
]


def play_sound(name: str):
    # NSSound.play() only works on the main thread (voice recording callbacks,
    # Pomodoro tick). For background threads use afplay on the system sound file.
    sound_path = f"/System/Library/Sounds/{name}.aiff"
    import os
    if os.path.exists(sound_path):
        subprocess.Popen(["afplay", sound_path])
    else:
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
        self.last_ctrl      = 0.0
        self.last_ctrl_v    = 0.0
        self._ctrl_held     = False
        self.frontmost_app  = ""
        self._model_lock    = threading.Lock()
        self._log           = load_log()
        self._vad           = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        self._speech_seen   = False  # becomes True once VAD detects first speech
        self._last_speech   = 0.0   # timestamp of last frame with speech
        self._silence_timer = None

        # Pomodoro
        self._pomo_end       = 0.0   # epoch when timer expires
        self._pomo_title     = ""
        self._pomo_timer     = None
        self._pomo_warned    = False  # True after 5-min warning fires
        self._signal_mtime   = 0.0   # mtime of last processed signal file

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

        # Pomodoro menu
        self.pomo_status_item = rumps.MenuItem("🍅 No timer")
        pomo_menu = rumps.MenuItem("Pomodoro")
        pomo_menu.add(self.pomo_status_item)
        pomo_menu.add(None)
        for mins in POMO_PRESETS:
            item = rumps.MenuItem(f"  Start {mins} min", callback=self._pomo_start_manual)
            item._pomo_minutes = mins
            pomo_menu.add(item)
        pomo_menu.add(None)
        pomo_menu.add(rumps.MenuItem("  Stop timer", callback=self._pomo_stop_manual))

        self.menu = [
            self.status_item,
            None,
            self.recent_menu,
            None,
            model_menu,
            None,
            pomo_menu,
            None,
        ]

        threading.Thread(target=self._load_model, args=(model_name,), daemon=True).start()
        self.listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self.listener.start()
        # Poll for auto-start signals from session-contract hook
        threading.Thread(target=self._signal_poller, daemon=True).start()

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
            self.model = whisper.load_model(name, device="cpu")
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

    def _on_release(self, key):
        if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            self._ctrl_held = False

    def _on_press(self, key):
        now = time.time()

        if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            self._ctrl_held = True
            is_double = (now - self.last_ctrl) < DOUBLE_TAP_WINDOW
            self.last_ctrl = now
            if not is_double:
                return
            if not self.recording:
                self._start_recording()
            else:
                self._stop_recording()

        elif self._ctrl_held and key == keyboard.KeyCode.from_char('v'):
            is_double = (now - self.last_ctrl_v) < DOUBLE_TAP_WINDOW
            self.last_ctrl_v = now
            if not is_double:
                return
            threading.Thread(target=self._paste_clipboard_image, daemon=True).start()

    # ── Recording ────────────────────────────────────────────────────────────

    def _audio_callback(self, indata, frame_count, time_info, status):
        if not self.recording:
            return
        self.audio_frames.append(indata.copy())

        # Convert float32 → 16-bit PCM for VAD
        pcm = (indata[:, 0] * 32767).astype(np.int16).tobytes()
        # Feed complete 30ms frames to VAD
        for i in range(0, len(pcm) - VAD_FRAME_BYTES + 1, VAD_FRAME_BYTES):
            frame = pcm[i:i + VAD_FRAME_BYTES]
            try:
                if self._vad.is_speech(frame, SAMPLE_RATE):
                    self._speech_seen = True
                    self._last_speech = time.time()
            except Exception:
                pass

    def _start_recording(self):
        if self.model is None:
            rumps.notification("Voice Input", "", "Model still loading, please wait.")
            return
        # Capture frontmost app NOW before focus can shift
        result = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to name of first process whose frontmost is true'],
            capture_output=True, text=True,
        )
        self.frontmost_app = result.stdout.strip()

        self.recording      = True
        self.audio_frames   = []
        self._speech_seen   = False
        self._last_speech   = 0.0
        self.title          = ICON_RECORDING
        self.status_item.title = "Status: Recording..."
        play_sound(SOUND_START)
        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1,
            dtype="float32", callback=self._audio_callback,
        )
        self.stream.start()
        self._silence_timer = threading.Timer(1.0, self._silence_watchdog)
        self._silence_timer.daemon = True
        self._silence_timer.start()

    def _silence_watchdog(self):
        if not self.recording:
            return
        # Only auto-stop after speech has been detected at least once
        if self._speech_seen and time.time() - self._last_speech >= TRAILING_SILENCE:
            self._stop_recording()
        else:
            self._silence_timer = threading.Timer(0.2, self._silence_watchdog)
            self._silence_timer.daemon = True
            self._silence_timer.start()

    def _stop_recording(self):
        self.recording = False
        if self._silence_timer:
            self._silence_timer.cancel()
            self._silence_timer = None
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
            result = self.model.transcribe(
                audio, fp16=False,
                initial_prompt="Use proper punctuation, capitalization, and formatting."
            )

        text = result["text"].strip()
        if not text:
            self._reset_idle("No speech detected.")
            return

        # Log + update menu
        append_transcript(self._log, text, self.model_name)
        self._refresh_recent_menu()

        # Re-activate the original window then paste
        pyperclip.copy(text)
        app = getattr(self, "frontmost_app", "")
        if app:
            subprocess.run(
                ["osascript", "-e", f'tell application "{app}" to activate'],
                capture_output=True,
            )
            time.sleep(0.15)
        subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to keystroke "v" using command down'],
            capture_output=True,
        )

        self._reset_idle("Ready")

    # ── Pomodoro ─────────────────────────────────────────────────────────────

    def _pomo_start(self, minutes: int, title: str = ""):
        if self._pomo_timer:
            self._pomo_timer.cancel()
        self._pomo_end    = time.time() + minutes * 60
        self._pomo_title  = title or f"{minutes} min session"
        self._pomo_warned = False
        self._pomo_tick()

    def _pomo_start_manual(self, sender):
        self._pomo_start(sender._pomo_minutes)

    def _pomo_stop_manual(self, _):
        if self._pomo_timer:
            self._pomo_timer.cancel()
            self._pomo_timer = None
        self._pomo_end = 0.0
        self.pomo_status_item.title = "🍅 No timer"
        self.title = ICON_IDLE
        POMODORO_STATE.unlink(missing_ok=True)

    def _pomo_tick(self):
        remaining = self._pomo_end - time.time()

        if remaining <= 0:
            self.pomo_status_item.title = "🍅 No timer"
            self.title = ICON_IDLE
            POMODORO_STATE.unlink(missing_ok=True)
            play_sound(SOUND_POMO)
            rumps.notification(
                "Pomodoro",
                self._pomo_title,
                "Time's up — take a break.",
                sound=False,
            )
            self._pomo_timer = None
            return

        mins = int(remaining // 60)
        secs = int(remaining % 60)

        # 5-min warning
        if not self._pomo_warned and remaining <= POMO_WARN_MIN * 60:
            self._pomo_warned = True
            play_sound(SOUND_POMO)
            rumps.notification(
                "Pomodoro",
                self._pomo_title,
                f"{POMO_WARN_MIN} minutes left.",
                sound=False,
            )

        self.pomo_status_item.title = f"🍅 {mins}:{secs:02d} remaining"
        # Show countdown in menu bar icon when not recording/processing
        if not self.recording and self.title not in (ICON_PROCESSING, ICON_LOADING):
            self.title = f"🍅 {mins}m"
        # Write live state so context-monitor.py can read it without waiting for a turn
        try:
            sid = ACTIVE_SID_FILE.read_text().strip() if ACTIVE_SID_FILE.exists() else ""
            POMODORO_STATE.write_text(json.dumps({
                "session_id": sid,
                "end_ts": self._pomo_end,
                "title": self._pomo_title,
            }))
        except Exception:
            pass
        self._pomo_timer = threading.Timer(1.0, self._pomo_tick)
        self._pomo_timer.daemon = True
        self._pomo_timer.start()

    def _signal_poller(self):
        """Check for pomodoro-signal.json written by session-contract hook."""
        while True:
            time.sleep(3)
            try:
                if not POMODORO_SIGNAL.exists():
                    continue
                mtime = POMODORO_SIGNAL.stat().st_mtime
                if mtime <= self._signal_mtime:
                    continue
                self._signal_mtime = mtime
                signal = json.loads(POMODORO_SIGNAL.read_text())
                minutes = int(signal.get("minutes", 50))
                title   = signal.get("title", "")
                self._pomo_start(minutes, title)
            except Exception:
                pass

    # ── Clipboard image paste ────────────────────────────────────────────────

    def _next_image_path(self) -> Path:
        d = current_images_dir()
        d.mkdir(parents=True, exist_ok=True)
        existing = list(d.glob("image_*.png"))
        nums = []
        for p in existing:
            try:
                nums.append(int(p.stem.split("_")[1]))
            except (IndexError, ValueError):
                pass
        n = (max(nums) + 1) if nums else 1
        return d / f"image_{n:03d}.png"

    def _clipboard_image(self):
        pb = NSPasteboard.generalPasteboard()
        for fmt, ext in _IMG_TYPES:
            data = pb.dataForType_(fmt)
            if data:
                return bytes(data), ext
        return None, None

    def _paste_clipboard_image(self):
        # Capture frontmost app before anything shifts focus
        result = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to name of first process whose frontmost is true'],
            capture_output=True, text=True,
        )
        active_app = result.stdout.strip()

        data, fmt = self._clipboard_image()
        if not data:
            self.status_item.title = "Status: No image in clipboard"
            threading.Timer(2.0, lambda: self._reset_idle("Ready")).start()
            return

        out = self._next_image_path()
        if fmt == "tiff":
            with tempfile.NamedTemporaryFile(suffix=".tiff", delete=False) as f:
                f.write(data)
                tmp = Path(f.name)
            subprocess.run(
                ["sips", "-s", "format", "png", str(tmp), "--out", str(out)],
                capture_output=True,
            )
            tmp.unlink(missing_ok=True)
        else:
            out.write_bytes(data)

        if not out.exists() or out.stat().st_size == 0:
            self.status_item.title = "Status: Image save failed"
            threading.Timer(2.0, lambda: self._reset_idle("Ready")).start()
            return

        ref = f"@{out}"
        subprocess.run(["pbcopy"], input=ref.encode(), check=True)
        play_sound(SOUND_IMAGE)
        self.status_item.title = f"Status: {out.name} → pasting…"

        if active_app:
            subprocess.run(
                ["osascript", "-e", f'tell application "{active_app}" to activate'],
                capture_output=True,
            )
            time.sleep(0.15)
        subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to keystroke "v" using command down'],
            capture_output=True,
        )
        self._reset_idle("Ready")

    def _reset_idle(self, status: str):
        # Restore Pomodoro countdown in icon if a timer is still running
        if self._pomo_end > time.time():
            remaining = self._pomo_end - time.time()
            self.title = f"🍅 {int(remaining // 60)}m"
        else:
            self.title = ICON_IDLE
        self.status_item.title = f"Status: {status}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL, choices=MODELS)
    args = parser.parse_args()
    VoiceApp(args.model).run()


if __name__ == "__main__":
    main()
