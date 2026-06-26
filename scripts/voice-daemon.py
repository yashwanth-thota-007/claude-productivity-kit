#!/usr/bin/env python3
"""
Voice input daemon — runs in background, listens for a global hotkey.
Hold Cmd+Shift+V to record, release to transcribe and paste to the
previously focused window.

Requires Accessibility permission (System Settings → Privacy → Accessibility).
Run once manually to trigger the permission prompt, then add to login items.

Usage:
  python3 voice-daemon.py               # default: base model, Cmd+Shift+V
  python3 voice-daemon.py --model small # better accuracy
"""
import sys, argparse, threading, time
import numpy as np
import sounddevice as sd
import whisper, pyperclip
from pynput import keyboard
from AppKit import NSApplication, NSApp
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    kCGHIDEventTap,
    CGEventSetFlags,
    kCGEventFlagMaskCommand,
)

SAMPLE_RATE       = 16000
DOUBLE_TAP_WINDOW = 0.4   # seconds between two Ctrl presses to count as double-tap

# --- State ---
recording        = False
audio_frames     = []
stream           = None
model_ref        = None
last_ctrl_time   = 0.0


def audio_callback(indata, frame_count, time_info, status):
    if recording:
        audio_frames.append(indata.copy())


def paste_to_active_window(text: str):
    """Copy text to clipboard then fire Cmd+V into whatever window is focused."""
    pyperclip.copy(text)
    time.sleep(0.1)
    for key_down in (True, False):
        evt = CGEventCreateKeyboardEvent(None, 0x09, key_down)  # 0x09 = V
        CGEventSetFlags(evt, kCGEventFlagMaskCommand)
        CGEventPost(kCGHIDEventTap, evt)


def transcribe_and_paste():
    global audio_frames
    if not audio_frames:
        print("[voice] No audio captured.")
        return
    audio = np.concatenate(audio_frames, axis=0).flatten()
    audio_frames = []
    if len(audio) < SAMPLE_RATE:
        print("[voice] Too short, ignoring.")
        return
    print("[voice] Transcribing...")
    result = model_ref.transcribe(audio, fp16=False)
    text = result["text"].strip()
    if not text:
        print("[voice] No speech detected.")
        return
    print(f"[voice] → {text}")
    paste_to_active_window(text)


def on_press(key):
    global recording, stream, audio_frames, last_ctrl_time

    if key != keyboard.Key.ctrl_l and key != keyboard.Key.ctrl_r:
        return

    now = time.time()
    is_double_tap = (now - last_ctrl_time) < DOUBLE_TAP_WINDOW
    last_ctrl_time = now

    if not is_double_tap:
        return  # first tap — just arm it

    # Double-tap detected — toggle recording
    if not recording:
        recording = True
        audio_frames = []
        stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                dtype="float32", callback=audio_callback)
        stream.start()
        print("[voice] Recording... (double-tap Ctrl to stop)")
    else:
        recording = False
        if stream:
            stream.stop()
            stream.close()
            stream = None
        threading.Thread(target=transcribe_and_paste, daemon=True).start()


def on_release(key):
    pass  # nothing needed — toggle is driven by press only


def main():
    global model_ref
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="small",
                        choices=["tiny", "base", "small", "medium", "large"])
    args = parser.parse_args()

    print(f"[voice] Loading Whisper '{args.model}' model...")
    model_ref = whisper.load_model(args.model)
    print("[voice] Ready. Double-tap Ctrl to START recording, double-tap again to STOP + paste.")
    print("[voice] Ctrl+C to quit.\n")

    with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
        listener.join()


if __name__ == "__main__":
    main()
