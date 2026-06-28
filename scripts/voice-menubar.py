#!/usr/bin/env python3
"""
Voice input + image paste + voice-to-Claude — macOS menu bar app.
Double-tap Ctrl  → start/stop recording, transcribes via Whisper, pastes into active window.
Double-tap Cmd   → start/stop recording, transcribes via Whisper, sends directly to Claude CLI (submits).
Double Ctrl+V    → save clipboard image to ~/.claude/paste-images/, paste @path into active window.

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
from AppKit import (
    NSSound, NSPasteboard,
    NSWindow, NSTextField, NSScrollView, NSTextView, NSButton,
    NSColor, NSFont, NSMakeRect,
    NSWindowStyleMaskBorderless, NSBackingStoreBuffered,
    NSFloatingWindowLevel,
)
from WebKit import WKWebView, WKWebViewConfiguration
from Foundation import NSLocale
from Speech import (
    SFSpeechRecognizer,
    SFSpeechAudioBufferRecognitionRequest,
    SFSpeechRecognizerAuthorizationStatus,
)
from AVFoundation import AVAudioEngine, AVAudioSession

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
ICON_CLAUDE_REC = "🤖"
ICON_PROCESSING = "⏳"
ICON_LOADING    = "⌛"

SOUND_START      = "Ping"
SOUND_STOP       = "Pop"
SOUND_IMAGE      = "Glass"
SOUND_POMO       = "Sosumi"
SOUND_SCREENSHOT = "Purr"

LOG_PATH            = Path.home() / ".claude" / "voice-transcripts.jsonl"
IMAGES_BASE         = Path.home() / ".claude" / "paste-images"
ACTIVE_SID_FILE     = Path.home() / ".claude" / "active-session-id"
POMODORO_SIGNAL     = Path.home() / ".claude" / "pomodoro-signal.json"
POMODORO_STATE      = Path.home() / ".claude" / "pomodoro-state.json"
DAILY_BRIEF_SIGNAL  = Path.home() / ".claude" / "daily-brief-signal.json"
VOICE_SESSION_FILE  = Path.home() / ".claude" / "voice-session-id"
SETTINGS_FILE       = Path.home() / ".claude" / "voice-menubar-settings.json"

POMO_WARN_MIN = 5

SPEECH_LOCALE = "en-US"
WAKE_WORD     = "hey claude"

_AGENT_SYSTEM_PROMPT = (
    "You are a computer use agent on macOS with full bash access and Playwright MCP tools.\n\n"
    "ROUTING RULE — decide this first based on the goal:\n"
    "  - Goal involves a WEBSITE or BROWSER task (YouTube, GitHub, Google, any URL):\n"
    "    → Use Playwright MCP tools exclusively: playwright_navigate, playwright_click,\n"
    "      playwright_fill, playwright_screenshot, playwright_select, playwright_hover.\n"
    "      Never use osascript or screencapture for browser tasks.\n"
    "  - Goal involves NATIVE macOS UI (Finder, Settings, desktop apps, system prefs):\n"
    "    → Use the calibration loop below with screencapture + osascript.\n\n"
    "CALIBRATION RULE — for native UI only, mandatory before every click:\n"
    "Coordinates on this display may not match what you expect. Before clicking anything:\n"
    "  1. Estimate target (X, Y) from the last screenshot.\n"
    "  2. Move cursor (no click): `python3 -c \"import Quartz; Quartz.CGWarpMouseCursorPosition((X, Y))\"`\n"
    "  3. Screenshot WITH cursor visible: `screencapture /tmp/cu_screen.png` → attach @/tmp/cu_screen.png\n"
    "  4. If cursor is NOT on target, adjust X/Y and repeat steps 2-3 up to 4 times.\n"
    "  5. Only once confirmed on target: `osascript -e 'tell application \"System Events\" to click at {X, Y}'`\n\n"
    "OTHER RULES:\n"
    "- After every action, verify with a fresh screenshot before the next step.\n"
    "- To open an app: `open -a \"AppName\"`\n"
    "- To press Enter in native UI: `osascript -e 'tell application \"System Events\" to key code 36'`\n\n"
    "Start by deciding: is this a browser task or a native UI task? Then act.\n\nGoal: "
)
WAKE_RESTART_SECS = 45   # SFSpeechRecognizer tasks time out near 60s — restart early

# Configurable defaults (overridden by SETTINGS_FILE at runtime)
DEFAULT_SILENCE      = 1.5
DEFAULT_POMO_PRESETS = [25, 50, 90]
DEFAULT_OVERLAY_POS  = "top-right"
DEFAULT_WAKE_WORD    = False

SILENCE_OPTIONS          = [0.5, 1.0, 1.5, 2.0, 3.0]
OVERLAY_POSITIONS        = ["top-right", "top-left", "bottom-right", "bottom-left"]
POMO_PRESET_OPTIONS      = [15, 25, 50, 90, 120]
FOCUS_GUARD_MULTIPLIER = 2       # threshold = Pomodoro duration × this
FOCUS_BREAK_THRESHOLD  = 15 * 60  # 15 min gap resets accumulated focus

CLAUDE_SETTINGS_FILE = Path.home() / ".claude" / "settings.json"


def _build_claude_env() -> dict:
    """Merge settings.json env block into current os.environ so the claude subprocess
    inherits all Bedrock routing, model config, and feature flags."""
    import os
    env = dict(os.environ)
    try:
        cfg = json.loads(CLAUDE_SETTINGS_FILE.read_text())
        for k, v in cfg.get("env", {}).items():
            env[k] = str(v)
    except Exception:
        pass
    return env


def _claude_model() -> str | None:
    """Return the model from settings.json, or None to let claude use its default."""
    try:
        cfg = json.loads(CLAUDE_SETTINGS_FILE.read_text())
        return cfg.get("model")
    except Exception:
        return None


def load_settings() -> dict:
    defaults = {
        "silence":      DEFAULT_SILENCE,
        "pomo_presets": DEFAULT_POMO_PRESETS,
        "overlay_pos":  DEFAULT_OVERLAY_POS,
        "wake_word":    DEFAULT_WAKE_WORD,
    }
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text())
            defaults.update(data)
        except Exception:
            pass
    return defaults


def save_settings(cfg: dict):
    SETTINGS_FILE.write_text(json.dumps(cfg, indent=2))


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


import objc
from Foundation import NSObject


class LiveTranscriber:
    """Real-time speech → text using SFSpeechRecognizer + AVAudioEngine.

    Calls on_partial(text) as the user speaks.
    Calls on_final(text) when stop() is called.
    Auto-stops after SPEECH_SILENCE seconds of silence.
    """

    def __init__(self, on_partial, on_final, on_stop, silence: float = DEFAULT_SILENCE):
        self._on_partial = on_partial
        self._on_final   = on_final
        self._on_stop    = on_stop
        self._silence    = silence
        locale  = NSLocale.alloc().initWithLocaleIdentifier_(SPEECH_LOCALE)
        self._recognizer = SFSpeechRecognizer.alloc().initWithLocale_(locale)
        self._engine     = AVAudioEngine.alloc().init()
        self._request    = None
        self._task       = None
        self._last_text  = ""
        self._last_ts    = time.time()
        self._watchdog   = None
        self._stopped    = False

    def start(self):
        self._request  = SFSpeechAudioBufferRecognitionRequest.alloc().init()
        self._request.setShouldReportPartialResults_(True)
        self._stopped  = False
        self._last_text = ""
        self._last_ts  = time.time()

        input_node = self._engine.inputNode()
        fmt = input_node.outputFormatForBus_(0)

        def _handler(result, error):
            if self._stopped:
                return
            if result:
                text = result.bestTranscription().formattedString()
                if text != self._last_text:
                    self._last_text = text
                    self._last_ts   = time.time()
                    self._on_partial(text)
            if error:
                self._do_stop()

        self._task = self._recognizer.recognitionTaskWithRequest_resultHandler_(
            self._request, _handler
        )

        input_node.installTapOnBus_bufferSize_format_block_(
            0, 1024, fmt,
            lambda buf, when: self._request.appendAudioPCMBuffer_(buf)
        )
        self._engine.prepare()
        self._engine.startAndReturnError_(None)

        self._watchdog = threading.Thread(target=self._silence_watchdog, daemon=True)
        self._watchdog.start()

    def _silence_watchdog(self):
        while not self._stopped:
            time.sleep(0.2)
            if self._last_text and time.time() - self._last_ts >= self._silence:
                self._do_stop()
                return

    def stop(self):
        """Manual stop — same path as auto."""
        self._do_stop()

    def _do_stop(self):
        if self._stopped:
            return
        self._stopped = True
        try:
            self._engine.inputNode().removeTapOnBus_(0)
            self._engine.stop()
            self._request.endAudio()
            if self._task:
                self._task.cancel()
        except Exception:
            pass
        self._on_final(self._last_text)
        self._on_stop()

class WakeWordListener:
    """Always-on recogniser that fires on_triggered() when WAKE_WORD is heard.

    Restarts itself every WAKE_RESTART_SECS to avoid SFSpeechRecognizer's ~60s
    task timeout. Paused during active recording so the engines don't conflict.
    """

    def __init__(self, on_triggered):
        self._on_triggered = on_triggered
        self._stopped      = True
        self._paused       = False
        self._lock         = threading.Lock()
        self._engine       = None
        self._task         = None
        self._request      = None
        self._restart_timer = None
        locale = NSLocale.alloc().initWithLocaleIdentifier_(SPEECH_LOCALE)
        self._recognizer = SFSpeechRecognizer.alloc().initWithLocale_(locale)

    def start(self):
        with self._lock:
            if not self._stopped:
                return
            self._stopped = False
        self._run_cycle()

    def stop(self):
        with self._lock:
            self._stopped = True
        self._teardown()

    def pause(self):
        """Called when main recording starts — silence the wake listener."""
        self._paused = True
        self._teardown()

    def resume(self):
        """Called when main recording ends — restart wake listener."""
        self._paused = False
        with self._lock:
            if not self._stopped:
                self._run_cycle()

    def _run_cycle(self):
        if self._stopped or self._paused:
            return
        try:
            self._engine  = AVAudioEngine.alloc().init()
            self._request = SFSpeechAudioBufferRecognitionRequest.alloc().init()
            self._request.setShouldReportPartialResults_(True)

            def _handler(result, error):
                if self._stopped or self._paused:
                    return
                if result:
                    text = result.bestTranscription().formattedString().lower()
                    if WAKE_WORD in text:
                        self._teardown()
                        self._on_triggered()
                        return
                if error:
                    # Restart on error (e.g. timeout)
                    self._teardown()
                    threading.Timer(0.5, self._run_cycle).start()

            self._task = self._recognizer.recognitionTaskWithRequest_resultHandler_(
                self._request, _handler
            )
            input_node = self._engine.inputNode()
            fmt = input_node.outputFormatForBus_(0)
            input_node.installTapOnBus_bufferSize_format_block_(
                0, 1024, fmt,
                lambda buf, when: self._request.appendAudioPCMBuffer_(buf) if not self._stopped else None,
            )
            self._engine.prepare()
            self._engine.startAndReturnError_(None)

            # Proactive restart before 60s timeout
            self._restart_timer = threading.Timer(WAKE_RESTART_SECS, self._restart)
            self._restart_timer.daemon = True
            self._restart_timer.start()
        except Exception:
            threading.Timer(1.0, self._run_cycle).start()

    def _restart(self):
        if self._stopped or self._paused:
            return
        self._teardown()
        self._run_cycle()

    def _teardown(self):
        if self._restart_timer:
            self._restart_timer.cancel()
            self._restart_timer = None
        try:
            if self._engine:
                self._engine.inputNode().removeTapOnBus_(0)
                self._engine.stop()
            if self._request:
                self._request.endAudio()
            if self._task:
                self._task.cancel()
        except Exception:
            pass
        self._engine  = None
        self._request = None
        self._task    = None


class _MainThreadRunner(NSObject):
    """Tiny NSObject helper that runs a Python callable on the main thread.
    No @objc.python_method — run_ must be a real ObjC selector for performSelectorOnMainThread_ to find it.
    """
    def run_(self, _):
        self._fn()


_OVERLAY_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    background: #141416;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif;
    font-size: 13px;
    color: #e8e8e8;
    padding: 8px 10px 16px;
    overflow-x: hidden;
}
.bubble { margin-bottom: 10px; display: flex; flex-direction: column; }
.bubble.user  { align-items: flex-end; }
.bubble.assistant, .bubble.status { align-items: flex-start; }
.label {
    font-size: 10px;
    color: #888;
    margin-bottom: 3px;
    padding: 0 4px;
}
.body {
    max-width: 92%;
    padding: 7px 10px;
    border-radius: 12px;
    line-height: 1.5;
    word-break: break-word;
}
.bubble.user .body {
    background: #1a4a7a;
    border-bottom-right-radius: 3px;
}
.bubble.assistant .body {
    background: #2a2a2e;
    border-bottom-left-radius: 3px;
}
.bubble.status .body {
    background: transparent;
    color: #888;
    font-style: italic;
    font-size: 12px;
    padding: 4px 6px;
}
.bubble.partial .body { opacity: 0.6; }
/* Markdown elements */
p  { margin: 0 0 6px; }
p:last-child { margin-bottom: 0; }
code {
    background: #1e1e22;
    border-radius: 4px;
    padding: 1px 5px;
    font-family: "SF Mono", Menlo, monospace;
    font-size: 12px;
    color: #e06c75;
}
pre {
    background: #1e1e22;
    border-radius: 8px;
    padding: 10px;
    overflow-x: auto;
    margin: 6px 0;
}
pre code {
    background: none;
    padding: 0;
    color: #abb2bf;
    font-size: 12px;
    line-height: 1.5;
}
table {
    border-collapse: collapse;
    width: 100%;
    margin: 6px 0;
    font-size: 12px;
}
th, td {
    border: 1px solid #444;
    padding: 5px 8px;
    text-align: left;
}
th { background: #333; color: #ccc; }
tr:nth-child(even) td { background: #252528; }
blockquote {
    border-left: 3px solid #555;
    padding-left: 10px;
    color: #aaa;
    margin: 4px 0;
}
ul, ol { padding-left: 18px; margin: 4px 0; }
li { margin-bottom: 2px; }
strong { color: #fff; }
em { color: #bbb; }
a { color: #5bb3f5; text-decoration: none; }
img.thumb {
    max-width: 100%;
    max-height: 160px;
    border-radius: 6px;
    margin-bottom: 4px;
    display: block;
}
h1,h2,h3 { color: #fff; margin: 8px 0 4px; }
h1 { font-size: 15px; }
h2 { font-size: 14px; }
h3 { font-size: 13px; }
"""

_OVERLAY_HTML_SHELL = """<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<style>{css}</style>
</head><body id="body"></body></html>"""

_OVERLAY_JS_APPEND = """
(function() {{
    var body = document.getElementById('body');
    var div = document.createElement('div');
    div.innerHTML = {html_json};
    body.appendChild(div);
    window.scrollTo(0, document.body.scrollHeight);
}})();
"""

_OVERLAY_JS_UPDATE_LAST = """
(function() {{
    var body = document.getElementById('body');
    var divs = body.children;
    if (divs.length > 0) {{
        divs[divs.length - 1].innerHTML = {html_json};
    }} else {{
        var div = document.createElement('div');
        div.innerHTML = {html_json};
        body.appendChild(div);
    }}
    window.scrollTo(0, document.body.scrollHeight);
}})();
"""


def _md_to_html(text: str) -> str:
    import mistune
    return mistune.html(text)


def _bubble_html(role: str, text: str, img_path: str = "") -> str:
    extra_class = ""
    if role == "user_partial":
        label = "🎙"
        extra_class = "user partial"
        body = f"<em>{text or '…'}</em>"
    elif role == "user":
        label = "🎙"
        extra_class = "user"
        img_tag = f'<img class="thumb" src="file://{img_path}">' if img_path else ""
        body = img_tag + (f"<p>{text}</p>" if text else "")
    elif role == "status":
        label = ""
        extra_class = "status"
        body = f"<p>{text}</p>"
    else:  # assistant
        label = "Claude"
        extra_class = "assistant"
        body = _md_to_html(text) if text else "<em>…</em>"

    label_html = f'<div class="label">{label}</div>' if label else ""
    return f'<div class="bubble {extra_class}">{label_html}<div class="body">{body}</div></div>'


class VoiceOverlay:
    """Persistent HUD backed by WKWebView — renders markdown, tables, images."""

    W, H        = 400, 480
    MARGIN      = 16
    BTN_H       = 22
    MINI_H      = 36

    def __init__(self, position: str = "top-right"):
        self._window    = None
        self._wv        = None
        self._lines     = []   # list of (role, text, img_path)
        self._position  = position
        self._minimized = False
        self._visible   = False
        self._build_window()

    def _dispatch(self, fn):
        helper = _MainThreadRunner.alloc().init()
        helper._fn = fn
        helper.performSelectorOnMainThread_withObject_waitUntilDone_(
            "run:", None, False
        )

    def _compute_origin(self, frame):
        pos = self._position
        sw, sh = frame.size.width, frame.size.height
        if pos == "top-left":
            x, y = self.MARGIN, sh - self.H - self.MARGIN - 24
        elif pos == "bottom-right":
            x, y = sw - self.W - self.MARGIN, self.MARGIN
        elif pos == "bottom-left":
            x, y = self.MARGIN, self.MARGIN
        else:
            x, y = sw - self.W - self.MARGIN, sh - self.H - self.MARGIN - 24
        return x, y

    def reposition(self, position: str):
        def _fn():
            self._position = position
            from AppKit import NSScreen
            frame = NSScreen.mainScreen().frame()
            x, y  = self._compute_origin(frame)
            self._window.setFrameOrigin_((x, y))
        self._dispatch(_fn)

    def _build_window(self):
        from AppKit import NSScreen
        frame = NSScreen.mainScreen().frame()
        x, y  = self._compute_origin(frame)
        rect  = NSMakeRect(x, y, self.W, self.H)

        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            rect, NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False,
        )
        win.setLevel_(NSFloatingWindowLevel + 1)
        win.setOpaque_(False)
        win.setAlphaValue_(0.95)
        win.setIgnoresMouseEvents_(False)
        win.setBackgroundColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.10, 0.10, 0.12, 0.95)
        )

        cv = win.contentView()

        # Close button
        close_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(self.W - 28, self.H - self.BTN_H - 4, 24, self.BTN_H)
        )
        close_btn.setTitle_("✕")
        close_btn.setBezelStyle_(0)
        close_btn.setBordered_(False)
        close_btn.setFont_(NSFont.systemFontOfSize_(12.0))
        cv.addSubview_(close_btn)

        # Minimize button
        mini_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(self.W - 54, self.H - self.BTN_H - 4, 24, self.BTN_H)
        )
        mini_btn.setTitle_("–")
        mini_btn.setBezelStyle_(0)
        mini_btn.setBordered_(False)
        mini_btn.setFont_(NSFont.systemFontOfSize_(14.0))
        cv.addSubview_(mini_btn)

        # WKWebView fills area below buttons
        wv_rect = NSMakeRect(0, 0, self.W, self.H - self.BTN_H - 8)
        cfg = WKWebViewConfiguration.alloc().init()
        wv = WKWebView.alloc().initWithFrame_configuration_(wv_rect, cfg)
        # Disable WKWebView's own background so the NSWindow dark bg shows through
        wv.setValue_forKey_(False, "drawsBackground")
        cv.addSubview_(wv)

        self._window = win
        self._wv     = wv

        # base URL allows file:// image paths to load
        from Foundation import NSURL
        base_url = NSURL.fileURLWithPath_("/")
        shell = _OVERLAY_HTML_SHELL.format(css=_OVERLAY_CSS)
        wv.loadHTMLString_baseURL_(shell, base_url)

        # Wire buttons
        self._close_helper = _CloseHelper.alloc().init()
        self._close_helper._overlay = self
        close_btn.setTarget_(self._close_helper)
        close_btn.setAction_("close:")

        self._mini_helper = _MiniHelper.alloc().init()
        self._mini_helper._overlay = self
        mini_btn.setTarget_(self._mini_helper)
        mini_btn.setAction_("minimize:")

    def _js_append(self, role: str, text: str, img_path: str = ""):
        html = _bubble_html(role, text, img_path)
        js   = _OVERLAY_JS_APPEND.format(html_json=json.dumps(html))
        self._wv.evaluateJavaScript_completionHandler_(js, None)

    def _js_update_last(self, role: str, text: str, img_path: str = ""):
        html = _bubble_html(role, text, img_path)
        js   = _OVERLAY_JS_UPDATE_LAST.format(html_json=json.dumps(html))
        self._wv.evaluateJavaScript_completionHandler_(js, None)

    def show_listening(self):
        def _fn():
            self._lines.append(("user_partial", "", ""))
            self._js_append("user_partial", "")
            self._visible = True
            self._window.orderFrontRegardless()
        self._dispatch(_fn)

    def update_partial(self, text: str):
        def _fn():
            if self._lines and self._lines[-1][0] == "user_partial":
                self._lines[-1] = ("user_partial", text, "")
                self._js_update_last("user_partial", text)
        self._dispatch(_fn)

    def finalize_user(self, text: str, img_path: str = ""):
        def _fn():
            if self._lines and self._lines[-1][0] == "user_partial":
                self._lines[-1] = ("user", text, img_path)
                self._js_update_last("user", text, img_path)
            else:
                self._lines.append(("user", text, img_path))
                self._js_append("user", text, img_path)
            self._lines.append(("assistant", "", ""))
            self._js_append("assistant", "")
        self._dispatch(_fn)

    def stream_chunk(self, text: str):
        def _fn():
            if self._lines and self._lines[-1][0] == "assistant":
                self._lines[-1] = ("assistant", text, "")
                self._js_update_last("assistant", text)
            else:
                self._lines.append(("assistant", text, ""))
                self._js_append("assistant", text)
        self._dispatch(_fn)

    def show_transcribing(self, text: str):
        def _fn():
            if self._lines and self._lines[-1][0] in ("user_partial", "status"):
                self._lines[-1] = ("user", text, "")
                self._js_update_last("user", text)
            else:
                self._lines.append(("user", text, ""))
                self._js_append("user", text)
            self._lines.append(("assistant", "", ""))
            self._js_append("assistant", "")
        self._dispatch(_fn)

    def show_response(self, response: str):
        def _fn():
            if self._lines and self._lines[-1][0] in ("assistant", "status"):
                self._lines[-1] = ("assistant", response, "")
                self._js_update_last("assistant", response)
            else:
                self._lines.append(("assistant", response, ""))
                self._js_append("assistant", response)
            self._visible = True
            self._window.orderFrontRegardless()
        self._dispatch(_fn)

    def minimize(self):
        def _fn():
            if self._minimized:
                return
            self._minimized = True
            self._wv.setHidden_(True)
            from AppKit import NSScreen
            frame = NSScreen.mainScreen().frame()
            x, y  = self._compute_origin(frame)
            self._window.setFrame_display_(
                NSMakeRect(x, y + self.H - self.MINI_H, self.W, self.MINI_H), True
            )
            self._window.orderFrontRegardless()
        self._dispatch(_fn)

    def restore(self):
        def _fn():
            if not self._minimized:
                return
            self._minimized = False
            from AppKit import NSScreen
            frame = NSScreen.mainScreen().frame()
            x, y  = self._compute_origin(frame)
            self._window.setFrame_display_(
                NSMakeRect(x, y, self.W, self.H), True
            )
            self._wv.setHidden_(False)
            self._window.orderFrontRegardless()
        self._dispatch(_fn)

    def hide(self):
        def _fn():
            self._visible = False
            self._window.orderOut_(None)
        self._dispatch(_fn)

    def temp_hide(self):
        def _fn():
            self._window.orderOut_(None)
        self._dispatch(_fn)

    def temp_show(self):
        def _fn():
            self._window.orderFrontRegardless()
        self._dispatch(_fn)

    def show(self, text: str, auto_hide: bool = False):
        def _fn():
            self._lines.append(("assistant", text, ""))
            self._js_append("assistant", text)
            self._window.orderFrontRegardless()
        self._dispatch(_fn)

    def update(self, text: str):
        def _fn():
            if self._lines and self._lines[-1][0] in ("status", "user_partial"):
                self._lines[-1] = ("status", text, "")
                self._js_update_last("status", text)
            else:
                self._lines.append(("status", text, ""))
                self._js_append("status", text)
        self._dispatch(_fn)


class _CloseHelper(NSObject):
    def close_(self, sender):
        self._overlay.hide()


class _MiniHelper(NSObject):
    def minimize_(self, sender):
        if self._overlay._minimized:
            self._overlay.restore()
        else:
            self._overlay.minimize()


class VoiceApp(rumps.App):
    def __init__(self, model_name: str):
        super().__init__(ICON_LOADING, quit_button="Quit")
        self._cfg = load_settings()

        self.model_name   = model_name
        self.model        = None
        self.recording    = False
        self.audio_frames = []
        self.stream       = None
        self.last_ctrl         = 0.0
        self.last_ctrl_v       = 0.0
        self.last_cmd          = 0.0
        self.last_alt          = 0.0
        self._ctrl_held        = False
        self._cmd_held         = False
        self._alt_held           = False
        self._pending_screenshot = None  # @path to attach to next Claude prompt
        self._screenshot_busy    = False  # guard against chord re-firing while capture runs
        self._recording_for_claude = False
        self._agent_mode           = False
        self.frontmost_app     = ""
        self._overlay          = VoiceOverlay(position=self._cfg["overlay_pos"])
        self._model_lock    = threading.Lock()
        self._log           = load_log()
        self._vad           = webrtcvad.Vad(VAD_AGGRESSIVENESS)
        self._speech_seen   = False  # becomes True once VAD detects first speech
        self._last_speech   = 0.0   # timestamp of last frame with speech
        self._silence_timer = None
        self._live_t        = None  # LiveTranscriber instance (Claude mode)

        # Wake word
        self._wake_listener = WakeWordListener(on_triggered=self._on_wake_word)

        # Pomodoro
        self._pomo_end       = 0.0   # epoch when timer expires
        self._pomo_title     = ""
        self._pomo_timer      = None
        self._pomo_warned     = False
        self._signal_mtime    = 0.0
        self._pomo_started_at = 0.0
        self._pomo_ended_at   = 0.0

        # Focus guard — resets per session, threshold = duration × FOCUS_GUARD_MULTIPLIER
        self._focus_accumulated = 0.0
        self._focus_threshold   = 0
        self._focus_fired       = False
        self._focus_session_id  = ""     # session that owns current focus block

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

        # Voice Claude session menu
        self.voice_session_item = rumps.MenuItem("🤖 Voice Session: none")
        voice_menu = rumps.MenuItem("Voice Claude")
        voice_menu.add(self.voice_session_item)
        voice_menu.add(None)
        self._agent_mode_item = rumps.MenuItem("  Computer Use Agent", callback=self._toggle_agent_mode)
        self._agent_mode_item.state = False
        voice_menu.add(self._agent_mode_item)
        voice_menu.add(None)
        voice_menu.add(rumps.MenuItem("  New session", callback=self._new_voice_session))
        self._refresh_voice_session_item()

        # Pomodoro menu — pre-create one slot per possible preset value
        self.pomo_status_item = rumps.MenuItem("🍅 No timer")
        pomo_menu = rumps.MenuItem("Pomodoro")
        # Up to 3 recent session name slots (pre-created, updated by _refresh_session_slots)
        self._session_slots = [rumps.MenuItem("") for _ in range(3)]
        for slot in self._session_slots:
            pomo_menu.add(slot)
        pomo_menu.add(self.pomo_status_item)
        pomo_menu.add(None)
        self._refresh_session_slots()
        self._pomo_preset_slots = []
        for mins in POMO_PRESET_OPTIONS:
            active = mins in self._cfg["pomo_presets"]
            item   = rumps.MenuItem(f"  Start {mins} min", callback=self._pomo_start_manual)
            item._pomo_minutes = mins
            item._pomo_active  = active
            item.state         = active  # checkmark = active preset
            pomo_menu.add(item)
            self._pomo_preset_slots.append(item)
        pomo_menu.add(None)
        pomo_menu.add(rumps.MenuItem("  Stop timer", callback=self._pomo_stop_manual))
        self._pomo_menu = pomo_menu

        # Settings menu
        settings_menu = rumps.MenuItem("Settings")

        # Silence threshold
        silence_sub = rumps.MenuItem("  Silence threshold")
        self._silence_items = {}
        for s in SILENCE_OPTIONS:
            label = f"  {s}s"
            item = rumps.MenuItem(label, callback=self._set_silence)
            item._silence_val = s
            item.state = (s == self._cfg["silence"])
            silence_sub.add(item)
            self._silence_items[s] = item
        settings_menu.add(silence_sub)
        settings_menu.add(None)

        # Overlay position
        pos_sub = rumps.MenuItem("  Overlay position")
        self._pos_items = {}
        for p in OVERLAY_POSITIONS:
            item = rumps.MenuItem(f"  {p}", callback=self._set_overlay_pos)
            item._pos_val = p
            item.state = (p == self._cfg["overlay_pos"])
            pos_sub.add(item)
            self._pos_items[p] = item
        settings_menu.add(pos_sub)
        settings_menu.add(None)

        # Pomodoro presets (multi-select checkmarks)
        pomo_preset_sub = rumps.MenuItem("  Pomodoro presets")
        self._pomo_preset_cfg_items = {}
        for mins in POMO_PRESET_OPTIONS:
            item = rumps.MenuItem(f"  {mins} min", callback=self._toggle_pomo_preset)
            item._preset_mins = mins
            item.state = (mins in self._cfg["pomo_presets"])
            pomo_preset_sub.add(item)
            self._pomo_preset_cfg_items[mins] = item
        settings_menu.add(pomo_preset_sub)
        settings_menu.add(None)

        # Wake word toggle
        self._wake_item = rumps.MenuItem("  Wake word: \"Hey Claude\"", callback=self._toggle_wake_word)
        self._wake_item.state = self._cfg["wake_word"]
        settings_menu.add(self._wake_item)

        # Focus guard status + reset in Pomodoro menu
        self._focus_status_item = rumps.MenuItem("🧠 Focus: 0 sessions")
        self._focus_reset_item  = rumps.MenuItem("  Reset focus guard", callback=self._reset_focus_guard)
        pomo_menu.add(None)
        pomo_menu.add(self._focus_status_item)
        pomo_menu.add(self._focus_reset_item)

        self.menu = [
            self.status_item,
            None,
            self.recent_menu,
            None,
            model_menu,
            None,
            voice_menu,
            None,
            pomo_menu,
            None,
            settings_menu,
            None,
        ]

        threading.Thread(target=self._load_model, args=(model_name,), daemon=True).start()
        self.listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self.listener.start()
        threading.Thread(target=self._signal_poller, daemon=True).start()
        if self._cfg["wake_word"]:
            self._wake_listener.start()

    # ── Session slots ────────────────────────────────────────────────────────

    def _refresh_session_slots(self):
        """Show up to 3 most recent active sessions from contracts dir."""
        contracts_dir = Path.home() / ".claude" / "session-contracts"
        sessions = []
        if contracts_dir.exists():
            files = sorted(contracts_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            for f in files[:3]:
                try:
                    c = json.loads(f.read_text())
                    if c.get("_skipped"):
                        continue
                    title  = c.get("session_title", "untitled")
                    effort = c.get("effort", "normal")
                    icon   = {"quick": "⚡", "deep": "🔬"}.get(effort, "📋")
                    sessions.append(f"{icon} {title}")
                except Exception:
                    continue
        for i, slot in enumerate(self._session_slots):
            slot.title = sessions[i] if i < len(sessions) else ""

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
        elif key in (keyboard.Key.cmd_l, keyboard.Key.cmd_r):
            self._cmd_held = False
        elif key in (keyboard.Key.alt_l, keyboard.Key.alt_r):
            self._alt_held = False

    def _on_press(self, key):
        now = time.time()

        # Option+Ctrl chord — guard prevents re-firing while capture is in progress
        if not self._screenshot_busy:
            if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r) and self._alt_held:
                self._screenshot_busy = True
                threading.Thread(target=self._capture_screenshot, daemon=True).start()
                return
            if key in (keyboard.Key.alt_l, keyboard.Key.alt_r) and self._ctrl_held:
                self._screenshot_busy = True
                threading.Thread(target=self._capture_screenshot, daemon=True).start()
                return

        if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            self._ctrl_held = True
            is_double = (now - self.last_ctrl) < DOUBLE_TAP_WINDOW
            self.last_ctrl = now
            if not is_double:
                return
            if not self.recording:
                self._recording_for_claude = False
                self._start_recording()
            else:
                self._stop_recording()

        elif key in (keyboard.Key.cmd_l, keyboard.Key.cmd_r):
            self._cmd_held = True
            is_double = (now - self.last_cmd) < DOUBLE_TAP_WINDOW
            self.last_cmd = now
            if not is_double:
                return
            if not self.recording:
                self._recording_for_claude = True
                self._start_recording()
            else:
                self._stop_recording()

        elif self._ctrl_held and key == keyboard.KeyCode.from_char('v'):
            is_double = (now - self.last_ctrl_v) < DOUBLE_TAP_WINDOW
            self.last_ctrl_v = now
            if not is_double:
                return
            threading.Thread(target=self._paste_clipboard_image, daemon=True).start()

        elif key in (keyboard.Key.alt_l, keyboard.Key.alt_r):
            self._alt_held = True

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

    def _on_wake_word(self):
        """Wake word detected — start Claude recording hands-free."""
        if self.recording:
            return
        self._recording_for_claude = True
        self._start_recording()

    def _toggle_wake_word(self, sender):
        enabled = not self._cfg["wake_word"]
        self._cfg["wake_word"] = enabled
        save_settings(self._cfg)
        self._wake_item.state = enabled
        if enabled:
            self._wake_listener.start()
            self.status_item.title = "Status: Wake word ON — say \"Hey Claude\""
        else:
            self._wake_listener.stop()
            self.status_item.title = "Status: Wake word OFF"
        threading.Timer(2.0, lambda: self._reset_idle("Ready")).start()

    def _start_recording(self):
        # Pause wake listener so its AVAudioEngine tap doesn't conflict
        self._wake_listener.pause()
        result = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to name of first process whose frontmost is true'],
            capture_output=True, text=True,
        )
        self.frontmost_app = result.stdout.strip()
        self.recording = True
        self.title = ICON_CLAUDE_REC if self._recording_for_claude else ICON_RECORDING
        self.status_item.title = "Status: Recording for Claude..." if self._recording_for_claude else "Status: Recording..."
        play_sound(SOUND_START)

        if self._recording_for_claude:
            self._overlay.show_listening()
            self._live_t = LiveTranscriber(
                on_partial=self._overlay.update_partial,
                on_final=self._on_live_final,
                on_stop=self._on_live_stopped,
                silence=self._cfg["silence"],
            )
            self._live_t.start()
        else:
            if self.model is None:
                rumps.notification("Voice Input", "", "Model still loading, please wait.")
                self.recording = False
                self.title = ICON_IDLE
                return
            self.audio_frames = []
            self._speech_seen = False
            self._last_speech = 0.0
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
        if self._speech_seen and time.time() - self._last_speech >= TRAILING_SILENCE:
            self._stop_recording()
        else:
            self._silence_timer = threading.Timer(0.2, self._silence_watchdog)
            self._silence_timer.daemon = True
            self._silence_timer.start()

    def _stop_recording(self):
        self.recording = False
        if self._recording_for_claude:
            if self._live_t:
                self._live_t.stop()   # triggers on_final → on_stop
            return
        # Whisper paste mode
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

    def _on_live_final(self, text: str):
        """SFSpeechRecognizer delivered final text."""
        self._live_final_text = text
        img_path = self._pending_screenshot or ""
        self._overlay.finalize_user(text, img_path=img_path)
        self.title = ICON_PROCESSING
        self.status_item.title = "Status: Asking Claude..."

    def _on_live_stopped(self):
        """AVAudioEngine fully stopped — now stream to Claude."""
        play_sound(SOUND_STOP)
        text = getattr(self, "_live_final_text", "")
        if not text.strip():
            self._reset_idle("No speech detected.")
            self._wake_listener.resume()
            return
        append_transcript(self._log, text, "live")
        self._refresh_recent_menu()
        threading.Thread(target=self._send_to_claude, args=(text,), daemon=True).start()

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
            # initial_prompt only for paste mode — in Claude mode omit it to
            # prevent Whisper from leaking the seed into short/unclear audio
            kwargs = {"language": "en"} if self._recording_for_claude else {
                "language": "en",
                "initial_prompt": "Use proper punctuation, capitalization, and formatting."
            }
            result = self.model.transcribe(audio, fp16=False, **kwargs)

        text = result["text"].strip()
        if not text:
            if self._recording_for_claude:
                self._overlay.hide()
            self._reset_idle("No speech detected.")
            return

        # Log + update menu
        append_transcript(self._log, text, self.model_name)
        self._refresh_recent_menu()

        if self._recording_for_claude:
            self._send_to_claude(text)
        else:
            self._paste_text(text)

        self._reset_idle("Ready")
        self._wake_listener.resume()

    def _paste_text(self, text: str):
        """Paste text into the previously focused window."""
        pyperclip.copy(text)
        app = getattr(self, "frontmost_app", "")
        if app:
            subprocess.run(
                ["osascript", "-e", f'tell application "System Events" to set frontmost of first process whose name is "{app}" to true'],
                capture_output=True,
            )
            time.sleep(0.15)
        subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to keystroke "v" using command down'],
            capture_output=True,
        )

    def _capture_screenshot(self):
        """Option+Ctrl — region screenshot → save to session folder → paste @path."""
        # Pause wake listener — screencapture takes mic/audio exclusively and crashes the tap
        self._wake_listener.pause()
        result = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to name of first process whose frontmost is true'],
            capture_output=True, text=True,
        )
        active_app = result.stdout.strip()

        # Raise the target window to front so screencapture freezes the screen with it visible.
        # set frontmost is async — poll until confirmed or bail after 0.5s.
        if active_app:
            subprocess.run(
                ["osascript", "-e",
                 f'tell application "System Events" to set frontmost of first process whose name is "{active_app}" to true'],
                capture_output=True,
            )
            deadline = time.time() + 0.5
            while time.time() < deadline:
                time.sleep(0.05)
                check = subprocess.run(
                    ["osascript", "-e",
                     'tell application "System Events" to name of first process whose frontmost is true'],
                    capture_output=True, text=True,
                )
                if check.stdout.strip() == active_app:
                    break

        out = self._next_image_path()
        self.status_item.title = "Status: Select region…"

        overlay_was_visible = self._overlay._visible
        if overlay_was_visible:
            self._overlay.temp_hide()
            time.sleep(0.15)

        subprocess.run(
            ["/usr/sbin/screencapture", "-i", "-x", str(out)],
            capture_output=True,
        )

        if overlay_was_visible:
            self._overlay.temp_show()
        self._screenshot_busy = False

        if not out.exists() or out.stat().st_size == 0:
            self._reset_idle("Screenshot cancelled.")
            self._wake_listener.resume()
            return

        play_sound(SOUND_SCREENSHOT)

        if self.recording and self._recording_for_claude:
            self._pending_screenshot = str(out)
            self.status_item.title = f"Status: Screenshot ready — speak your prompt"
        else:
            ref = f"@{out}"
            subprocess.run(["pbcopy"], input=ref.encode(), check=True)
            self.status_item.title = f"Status: {out.name} → pasting…"
            time.sleep(0.3)
            if active_app:
                subprocess.run(
                    ["osascript", "-e",
                     f'tell application "System Events" to set frontmost of first process whose name is "{active_app}" to true'],
                    capture_output=True,
                )
                time.sleep(0.25)
            subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to keystroke "v" using command down'],
                capture_output=True,
            )
            self._reset_idle("Ready")
        self._wake_listener.resume()

    def _refresh_voice_session_item(self):
        if VOICE_SESSION_FILE.exists():
            sid = VOICE_SESSION_FILE.read_text().strip()
            # Try to show the human-readable session title from the contract
            contract_path = Path.home() / ".claude" / "session-contracts" / f"{sid}.json"
            title = ""
            if contract_path.exists():
                try:
                    c = json.loads(contract_path.read_text())
                    title = c.get("session_title", "")
                except Exception:
                    pass
            label = title[:32] if title else sid[:8] + "…"
            self.voice_session_item.title = f"🤖 {label}"
        else:
            self.voice_session_item.title = "🤖 Voice Session: none"

    def _new_voice_session(self, _=None):
        VOICE_SESSION_FILE.unlink(missing_ok=True)
        self._refresh_voice_session_item()
        self.status_item.title = "Status: Voice session reset"
        threading.Timer(2.0, lambda: self._reset_idle("Ready")).start()

    def _toggle_agent_mode(self, sender):
        self._agent_mode = not self._agent_mode
        sender.state = self._agent_mode
        label = "ON — speak a goal" if self._agent_mode else "OFF"
        self.status_item.title = f"Status: Computer Use Agent {label}"
        threading.Timer(2.0, lambda: self._reset_idle("Ready")).start()

    # ── Settings callbacks ───────────────────────────────────────────────────

    def _set_silence(self, sender):
        val = sender._silence_val
        self._cfg["silence"] = val
        save_settings(self._cfg)
        for s, item in self._silence_items.items():
            item.state = (s == val)
        self.status_item.title = f"Status: Silence → {val}s"
        threading.Timer(2.0, lambda: self._reset_idle("Ready")).start()

    def _set_overlay_pos(self, sender):
        pos = sender._pos_val
        self._cfg["overlay_pos"] = pos
        save_settings(self._cfg)
        for p, item in self._pos_items.items():
            item.state = (p == pos)
        self._overlay.reposition(pos)
        self.status_item.title = f"Status: Overlay → {pos}"
        threading.Timer(2.0, lambda: self._reset_idle("Ready")).start()

    def _toggle_pomo_preset(self, sender):
        mins    = sender._preset_mins
        presets = list(self._cfg["pomo_presets"])
        if mins in presets:
            if len(presets) == 1:
                return   # must keep at least one
            presets.remove(mins)
        else:
            presets.append(mins)
            presets.sort()
        sender.state = (mins in presets)
        self._cfg["pomo_presets"] = presets
        save_settings(self._cfg)
        self._rebuild_pomo_slots()

    def _rebuild_pomo_slots(self):
        """Sync checkmarks on Pomodoro start slots to current cfg["pomo_presets"]."""
        presets = self._cfg["pomo_presets"]
        for slot in self._pomo_preset_slots:
            active            = slot._pomo_minutes in presets
            slot._pomo_active = active
            slot.state        = active

    # ── Clipboard image ──────────────────────────────────────────────────────

    def _clipboard_image_for_voice(self) -> str:
        """Return @path prefix for any pending screenshot or clipboard image."""
        # Pending screenshot (Option+S taken during recording) takes priority
        if self._pending_screenshot:
            path = self._pending_screenshot
            self._pending_screenshot = None
            return f"@{path} "

        data, fmt = self._clipboard_image()
        if not data:
            return ""
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
        if out.exists() and out.stat().st_size > 0:
            return f"@{out} "
        return ""

    def _agent_session_name(self, goal: str) -> str:
        """Stable slug for the AgentFS session — reused across turns for the same goal."""
        import re
        slug = re.sub(r"[^a-z0-9]+", "-", goal.lower().strip())[:40].strip("-")
        return f"voice-{slug}" if slug else "voice-agent"

    def _agentfs_bin(self) -> str:
        import os
        for candidate in [
            os.path.expanduser("~/.cargo/bin/agentfs"),
            "/usr/local/bin/agentfs",
            "/opt/homebrew/bin/agentfs",
        ]:
            if os.path.exists(candidate):
                return candidate
        return "agentfs"

    def _ensure_agentfs_session(self, session_name: str):
        """Create the AgentFS session DB if it doesn't exist yet."""
        import os
        db = Path.home() / ".agentfs" / f"{session_name}.db"
        if not db.exists():
            subprocess.run(
                [self._agentfs_bin(), "init", session_name, "--base", str(Path.home())],
                capture_output=True, cwd=str(Path.home()),
            )

    def _agentfs_diff(self, session_name: str) -> str:
        """Return a short summary of what the agent changed."""
        try:
            result = subprocess.run(
                [self._agentfs_bin(), "diff", session_name],
                capture_output=True, text=True, timeout=10, cwd=str(Path.home()),
            )
            diff = result.stdout.strip()
            if not diff or "No changes" in diff:
                return ""
            # Trim to first 800 chars so overlay stays readable
            lines = diff.splitlines()
            summary = "\n".join(lines[:30])
            if len(lines) > 30:
                summary += f"\n… ({len(lines) - 30} more lines)"
            return f"\n\n---\n**Agent changed:**\n```\n{summary}\n```"
        except Exception:
            return ""

    _ART_INTENT_PHRASES = (
        "make art", "generate art", "turn into art", "convert to art",
        "algorithmic art", "particle art", "make it art", "art from this",
        "make this art", "generative art",
    )

    def _maybe_open_art(self, text: str) -> bool:
        """If the request looks like image-to-art, save clipboard image and open the artifact.
        Returns True if handled (caller should skip Claude call)."""
        low = text.lower()
        if not any(p in low for p in self._ART_INTENT_PHRASES):
            return False
        # Resolve image path — pending screenshot or clipboard
        if self._pending_screenshot:
            img_path = str(self._pending_screenshot)
            self._pending_screenshot = None
        else:
            data, fmt = self._clipboard_image()
            if not data:
                return False
            out = self._next_image_path()
            if fmt == "tiff":
                import tempfile
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
                return False
            img_path = str(out)

        art_html = Path.home() / ".claude" / "skills" / "algorithmic-art" / "image-to-art.html"
        # Encode image as base64 data URI — avoids file:// CORS block in Chrome/Safari
        import base64, mimetypes
        mime = mimetypes.guess_type(img_path)[0] or "image/png"
        b64 = base64.b64encode(Path(img_path).read_bytes()).decode()
        data_uri = f"data:{mime};base64,{b64}"
        # Write a tiny one-shot HTML wrapper that embeds the data URI and redirects
        # to the artifact with it encoded in sessionStorage (avoids URL length limits)
        launcher = Path(img_path).parent / "art-launcher.html"
        launcher.write_text(f"""<!DOCTYPE html><html><body><script>
sessionStorage.setItem('artImg','{data_uri}');
location.href='file://{art_html}';
</script></body></html>""")
        url = f"file://{launcher}"
        subprocess.Popen(["open", url])
        self._overlay.stream_chunk(f"Opening art generator with your image…\n`{Path(img_path).name}`")
        play_sound(SOUND_STOP)
        self._reset_idle("Ready")
        self._wake_listener.resume()
        return True

    def _send_to_claude(self, text: str):
        """Stream claude response, pushing text chunks to overlay as they arrive."""
        self.status_item.title = "Status: Asking Claude..."

        if self._maybe_open_art(text):
            return

        img_prefix = self._clipboard_image_for_voice()
        if self._agent_mode:
            # Include any attached screenshot so agent can see it
            prompt = f"{_AGENT_SYSTEM_PROMPT}{img_prefix}{text}"
        else:
            prompt = f"{img_prefix}{text}"

        claude_cmd = [
            "/opt/homebrew/bin/claude", "--print",
            "--output-format", "stream-json", "--verbose",
            "--dangerously-skip-permissions",
        ]
        model = _claude_model()
        if model:
            claude_cmd += ["--model", model]
        if VOICE_SESSION_FILE.exists():
            sid = VOICE_SESSION_FILE.read_text().strip()
            if sid:
                claude_cmd += ["--resume", sid]
        claude_cmd.append(prompt)

        # Wrap in AgentFS COW sandbox when agent mode is active
        if self._agent_mode:
            session_name = self._agent_session_name(text)
            self._ensure_agentfs_session(session_name)
            cmd = [self._agentfs_bin(), "run", "--session", session_name] + claude_cmd
        else:
            cmd = claude_cmd
            session_name = None

        accumulated = ""
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                env=_build_claude_env(), cwd=str(Path.home()),
            )
            for raw in proc.stdout:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                t = obj.get("type")
                if t == "assistant":
                    for block in obj.get("message", {}).get("content", []):
                        if block.get("type") == "text":
                            accumulated = block["text"]
                            self._overlay.stream_chunk(accumulated)
                elif t == "result":
                    sid = obj.get("session_id", "")
                    if sid:
                        VOICE_SESSION_FILE.write_text(sid)
                        self._refresh_voice_session_item()
                    if not accumulated:
                        accumulated = obj.get("result", "No response.")
                        self._overlay.stream_chunk(accumulated)
            proc.wait(timeout=5)
        except Exception as e:
            self._overlay.stream_chunk(f"Error: {e}")

        # Show AgentFS diff in overlay after agent run
        if self._agent_mode and session_name:
            diff_summary = self._agentfs_diff(session_name)
            if diff_summary:
                self._overlay.stream_chunk(accumulated + diff_summary)

        play_sound(SOUND_STOP)
        self._reset_idle("Ready")
        self._wake_listener.resume()

    # ── Pomodoro ─────────────────────────────────────────────────────────────

    def _pomo_start(self, minutes: int, title: str = ""):
        if self._pomo_timer:
            self._pomo_timer.cancel()
        now = time.time()
        self._pomo_started_at = now
        self._pomo_mins       = minutes
        self._pomo_end        = now + minutes * 60
        self._pomo_title  = title or f"{minutes} min session"
        self._pomo_warned = False
        self._pomo_tick()

    def _pomo_start_manual(self, sender):
        if not getattr(sender, "_pomo_active", True):
            return
        self._pomo_start(sender._pomo_minutes)

    def _pomo_stop_manual(self, _):
        if self._pomo_timer:
            self._pomo_timer.cancel()
            self._pomo_timer = None
        self._pomo_end = 0.0
        self.pomo_status_item.title = "🍅 No timer"
        self.title = ICON_IDLE
        POMODORO_STATE.unlink(missing_ok=True)

    def _accumulate_focus(self, elapsed_secs: float):
        self._focus_accumulated += elapsed_secs
        total_mins = int(self._focus_accumulated / 60)
        self._focus_status_item.title = f"🧠 Focus: {total_mins} min / {self._focus_threshold} min"
        if not self._focus_fired and self._focus_threshold > 0 and self._focus_accumulated >= self._focus_threshold * 60:
            self._focus_fired = True
            play_sound(SOUND_POMO)
            rumps.notification(
                "Focus Guard",
                f"{total_mins} min of focused work",
                "Time for a proper break — step away for 15+ minutes.",
                sound=False,
            )
            self._overlay.show(
                f"🧠 **Focus guard**\n\n{total_mins} minutes of focused work. "
                "Step away for at least 15 minutes."
            )

    def _reset_focus_guard(self, _=None):
        self._focus_accumulated = 0.0
        self._focus_threshold   = 0
        self._focus_fired       = False
        self._focus_status_item.title = "🧠 Focus: 0 min"
        self.status_item.title = "Status: Focus guard reset"
        threading.Timer(2.0, lambda: self._reset_idle("Ready")).start()

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
            self._pomo_timer    = None
            self._pomo_ended_at = time.time()
            pomo_mins = getattr(self, "_pomo_mins", 25)
            self._accumulate_focus(pomo_mins * 60)
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
        """Check for signal files written by external scripts."""
        self._brief_mtime = 0.0
        while True:
            time.sleep(3)
            try:
                # Pomodoro signal
                if POMODORO_SIGNAL.exists():
                    mtime = POMODORO_SIGNAL.stat().st_mtime
                    if mtime > self._signal_mtime:
                        self._signal_mtime = mtime
                        signal     = json.loads(POMODORO_SIGNAL.read_text())
                        minutes    = int(signal.get("minutes", 50))
                        title      = signal.get("title", "")
                        session_id = signal.get("session_id", "")
                        if session_id and session_id != self._focus_session_id:
                            self._focus_session_id  = session_id
                            self._focus_accumulated = 0.0
                            self._focus_threshold   = minutes * FOCUS_GUARD_MULTIPLIER
                            self._focus_fired       = False
                            self._focus_status_item.title = f"🧠 Focus: 0 min / {self._focus_threshold} min"
                        self._refresh_session_slots()
                        self._pomo_start(minutes, title)
            except Exception:
                pass

            try:
                # Daily brief signal
                if DAILY_BRIEF_SIGNAL.exists():
                    mtime = DAILY_BRIEF_SIGNAL.stat().st_mtime
                    if mtime > self._brief_mtime:
                        self._brief_mtime = mtime
                        signal = json.loads(DAILY_BRIEF_SIGNAL.read_text())
                        content = signal.get("content", "")
                        if content:
                            play_sound(SOUND_START)
                            self._overlay.show(content)
            except Exception:
                pass

            try:
                # Session-end summary signal (written by session-replay.py Stop hook)
                session_end_signal = Path.home() / ".claude" / "session-end-signal.json"
                if session_end_signal.exists():
                    mtime = session_end_signal.stat().st_mtime
                    if not hasattr(self, '_session_end_mtime'):
                        self._session_end_mtime = 0.0
                    if mtime > self._session_end_mtime:
                        self._session_end_mtime = mtime
                        signal = json.loads(session_end_signal.read_text())
                        content = signal.get("content", "")
                        if content and signal.get("type") == "session_end":
                            play_sound(SOUND_STOP)
                            self._overlay.show(f"**Session complete**\n\n{content}")
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
                ["osascript", "-e", f'tell application "System Events" to set frontmost of first process whose name is "{active_app}" to true'],
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
