#!/usr/bin/env python3
"""
Paste clipboard image into Claude CLI.

Reads image from macOS clipboard, saves to ~/.claude/paste-images/image_NNN.png,
copies "@<path>" to clipboard. Then Cmd+V anywhere in your Claude prompt
attaches it — same as drag-drop in VS Code.

Usage: cvimg
Then Cmd+V in your Claude CLI prompt to insert the @reference.
"""
import sys, subprocess, tempfile
from pathlib import Path

IMAGES_DIR = Path.home() / ".claude" / "paste-images"


def clipboard_image_data():
    from AppKit import NSPasteboard
    pb = NSPasteboard.generalPasteboard()
    for fmt, ext in [
        ("public.png", "png"),
        ("NSPasteboardTypePNG", "png"),
        ("public.tiff", "tiff"),
        ("NSPasteboardTypeTIFF", "tiff"),
    ]:
        data = pb.dataForType_(fmt)
        if data:
            return bytes(data), ext
    return None, None


def next_image_path() -> Path:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    existing = list(IMAGES_DIR.glob("image_*.png"))
    nums = []
    for p in existing:
        try:
            nums.append(int(p.stem.split("_")[1]))
        except (IndexError, ValueError):
            pass
    n = (max(nums) + 1) if nums else 1
    return IMAGES_DIR / f"image_{n:03d}.png"


def tiff_to_png(tiff_bytes: bytes, out: Path):
    with tempfile.NamedTemporaryFile(suffix=".tiff", delete=False) as f:
        f.write(tiff_bytes)
        tmp = Path(f.name)
    subprocess.run(
        ["sips", "-s", "format", "png", str(tmp), "--out", str(out)],
        capture_output=True,
    )
    tmp.unlink(missing_ok=True)


def main():
    data, fmt = clipboard_image_data()
    if not data:
        print("[cvimg] No image in clipboard.", file=sys.stderr)
        sys.exit(1)

    out = next_image_path()

    if fmt == "tiff":
        tiff_to_png(data, out)
    else:
        out.write_bytes(data)

    if not out.exists() or out.stat().st_size == 0:
        print("[cvimg] Failed to save image.", file=sys.stderr)
        sys.exit(1)

    ref = f"@{out}"
    subprocess.run(["pbcopy"], input=ref.encode(), check=True)
    print(f"[cvimg] {out.name} saved — @reference copied to clipboard. Cmd+V to attach.")


if __name__ == "__main__":
    main()
