#!/bin/sh
# Extract OAuth token from Claude CLI credentials and set as ANTHROPIC_API_KEY.
# The token is short-lived; restart the container if you get 401 errors.
set -e

CREDS="/root/.claude/.credentials.json"

if [ -f "$CREDS" ]; then
    TOKEN=$(python3 -c "
import json, sys
d = json.load(open('$CREDS'))
t = d.get('claudeAiOauth', {}).get('accessToken', '')
if not t:
    sys.exit('No accessToken found in credentials')
print(t, end='')
")
    export ANTHROPIC_API_KEY="$TOKEN"
else
    echo "Warning: $CREDS not found — falling back to ANTHROPIC_API_KEY env var" >&2
fi

exec python -m fracture.consumer --config /app/fracture.yaml
