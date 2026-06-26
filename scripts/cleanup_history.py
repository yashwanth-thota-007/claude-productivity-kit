#!/usr/bin/env python3
"""
Script to clean up Claude history entries older than 30 days.
"""

import json
import os
import time
import sys
import shutil
from datetime import datetime, timedelta

# Path to Claude history file
HISTORY_FILE = os.path.expanduser("~/.claude/history.jsonl")
BACKUP_DIR = os.path.expanduser("~/.claude/history_backups")

def backup_history_file():
    """Create a backup of the history file before modifying it."""
    if not os.path.exists(HISTORY_FILE):
        print(f"History file not found at {HISTORY_FILE}")
        return False

    # Create backup directory if it doesn't exist
    os.makedirs(BACKUP_DIR, exist_ok=True)

    # Create a backup with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(BACKUP_DIR, f"history_{timestamp}.jsonl")
    shutil.copy2(HISTORY_FILE, backup_file)
    print(f"Created backup at {backup_file}")
    return True

def cleanup_history(days=30):
    """Remove history entries older than the specified number of days."""
    if not os.path.exists(HISTORY_FILE):
        print(f"History file not found at {HISTORY_FILE}")
        return

    # Calculate the cutoff timestamp (milliseconds)
    cutoff_time = int((datetime.now() - timedelta(days=days)).timestamp() * 1000)

    # Create a new file with recent entries
    temp_file = HISTORY_FILE + ".new"
    kept_count = 0
    removed_count = 0

    with open(HISTORY_FILE, 'r') as infile, open(temp_file, 'w') as outfile:
        for line in infile:
            try:
                entry = json.loads(line.strip())
                if entry.get('timestamp', 0) >= cutoff_time:
                    outfile.write(line)
                    kept_count += 1
                else:
                    removed_count += 1
            except json.JSONDecodeError:
                # Keep lines that can't be parsed as JSON
                outfile.write(line)
                kept_count += 1

    # Replace the original file with the new one
    os.replace(temp_file, HISTORY_FILE)

    print(f"Cleanup complete. Removed {removed_count} old entries, kept {kept_count} recent entries.")

if __name__ == "__main__":
    # Parse command-line arguments
    days = 30  # Default
    if len(sys.argv) > 1:
        try:
            days = int(sys.argv[1])
        except ValueError:
            print(f"Invalid value for days: {sys.argv[1]}. Using default of 30 days.")

    print(f"Cleaning up history entries older than {days} days...")

    # Backup the file first
    if backup_history_file():
        # Clean up history
        cleanup_history(days)
    else:
        print("Backup failed. Aborting cleanup.")