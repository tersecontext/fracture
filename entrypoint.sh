#!/bin/sh
# Start the Fracture Redis consumer.
# Claude CLI auth comes from the ~/.claude volume mount.
set -e
exec python -m fracture.consumer --config /app/fracture.yaml
