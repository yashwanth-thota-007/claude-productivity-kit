#!/usr/bin/env python3
import pathlib

sig = pathlib.Path.home() / ".claude" / "tool-running.json"
sig.unlink(missing_ok=True)
