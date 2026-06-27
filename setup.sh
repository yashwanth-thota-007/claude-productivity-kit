#!/bin/bash
# Run once after cloning to personalise plists with your $HOME path.
# Copy settings.example.json → settings.json and fill in your values first.
set -e

CLAUDE_DIR="$(cd "$(dirname "$0")" && pwd)"

for plist in "$CLAUDE_DIR"/com.claude.*.plist; do
    sed -i '' "s|CLAUDE_HOME|$HOME|g" "$plist"
    echo "Patched: $plist"
done

echo ""
echo "Next steps:"
echo "  1. cp $CLAUDE_DIR/settings.example.json $CLAUDE_DIR/settings.json"
echo "  2. Edit settings.json — fill in AWS_PROFILE, AWS_REGION, model IDs"
echo "  3. launchctl load ~/Library/LaunchAgents/com.claude.voice-menubar.plist"
echo "  4. launchctl load ~/Library/LaunchAgents/com.claude.standup.plist"
