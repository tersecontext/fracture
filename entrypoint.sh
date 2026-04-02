#!/bin/sh
# Start the Fracture Redis consumer.
# Claude CLI auth comes from the ~/.claude volume mount (read-only).
set -e

# The claude CLI expects ~/.claude.json to exist. The read-only mount
# may only have a backup copy, so restore it if the main file is missing.
if [ ! -f /root/.claude.json ] && ls /root/.claude/backups/.claude.json.backup.* >/dev/null 2>&1; then
    LATEST=$(ls -t /root/.claude/backups/.claude.json.backup.* | head -1)
    cp "$LATEST" /root/.claude.json
    echo "Restored claude config from $LATEST"
fi

exec python -m fracture.consumer --config /app/fracture.yaml
