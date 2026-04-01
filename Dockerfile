FROM python:3.12-slim

# Install Node.js (LTS) for the claude CLI
RUN apt-get update && apt-get install -y --no-install-recommends \
        nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# Install claude-code globally so `claude -p` is available
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /app

COPY pyproject.toml ./
COPY src/ src/
COPY entrypoint.sh /entrypoint.sh

RUN pip install --no-cache-dir . && chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
