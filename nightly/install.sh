#!/bin/sh
# Installs the nightly eval as a launchd agent for this user, at 03:00.
# Undo: launchctl bootout gui/$(id -u)/dev.mobium.evals-nightly && rm ~/Library/LaunchAgents/dev.mobium.evals-nightly.plist
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
DEST="$HOME/Library/LaunchAgents/dev.mobium.evals-nightly.plist"
mkdir -p "$HERE/nightly/out" "$HOME/Library/LaunchAgents"
sed -e "s|__HERE__|$HERE|g" -e "s|__HOME__|$HOME|g" "$HERE/nightly/dev.mobium.evals-nightly.plist" > "$DEST"
plutil -lint "$DEST"
launchctl bootout "gui/$(id -u)/dev.mobium.evals-nightly" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$DEST"
launchctl print "gui/$(id -u)/dev.mobium.evals-nightly" | grep -E 'state|path' | head -3
