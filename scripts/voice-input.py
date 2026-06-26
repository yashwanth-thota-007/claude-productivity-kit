#!/usr/bin/env python3
"""
Voice input prototype — press Enter to start recording, Enter again to stop.
Transcribes locally via Whisper and copies result to clipboard.

Usage:
  python3 voice-input.py              # transcribe only, copy to clipboard
  python3 voice-input.py --paste      # also paste into active window
  python3 voice-input.py --model medium  # use a larger model (default: base)
"""
import sys, argparse, threading, numpy as np
import sounddevice as sd
import whisper, pyperclip, subprocess

SAMPLE_RATE = 16000


def record_until_enter() -> np.ndarray:
    frames = []
    stop = threading.Event()

    def callback(indata, frame_count, time_info, status):
        frames.append(indata.copy())

    print("Recording... press Enter to stop.")
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", callback=callback):
        input()  # blocks until Enter
        stop.set()

    if not frames:
        return np.array([], dtype="float32")
    return np.concatenate(frames, axis=0).flatten()


def paste_text():
    script = 'tell application "System Events" to keystroke "v" using command down'
    subprocess.run(["osascript", "-e", script], check=False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--paste", action="store_true", help="Paste into active window after transcribing")
    parser.add_argument("--model", default="base", choices=["tiny", "base", "small", "medium", "large"], help="Whisper model size")
    args = parser.parse_args()

    print(f"Loading Whisper '{args.model}' model (first run downloads it)...")
    model = whisper.load_model(args.model)
    print("Model ready.")

    print("\nPress Enter to START recording.")
    input()

    audio = record_until_enter()
    if len(audio) < SAMPLE_RATE:  # less than 1 second
        print("Recording too short, exiting.")
        sys.exit(1)

    print("Transcribing...")
    result = model.transcribe(audio, fp16=False)
    text = result["text"].strip()

    if not text:
        print("No speech detected.")
        sys.exit(1)

    print(f"\nTranscribed:\n  {text}\n")
    pyperclip.copy(text)
    print("Copied to clipboard.")

    if args.paste:
        paste_text()
        print("Pasted into active window.")


if __name__ == "__main__":
    main()
