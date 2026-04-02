# Stage 1: Build bd from source
FROM golang:1.25 AS bd-builder
WORKDIR /build
COPY --from=beads . .
RUN go build -o /bd ./cmd/bd

# Stage 2: Final image
FROM python:3.12-slim

# Install Node.js (LTS) for the claude CLI
RUN apt-get update && apt-get install -y --no-install-recommends \
        nodejs npm curl \
    && rm -rf /var/lib/apt/lists/*

# Install dolt
RUN curl -L https://github.com/dolthub/dolt/releases/latest/download/install.sh | bash

# Install claude-code globally so `claude -p` is available
RUN npm install -g @anthropic-ai/claude-code

# Install bd from build stage
COPY --from=bd-builder /bd /usr/local/bin/bd

WORKDIR /app

COPY pyproject.toml ./
COPY src/ src/
COPY entrypoint.sh /entrypoint.sh

RUN pip install --no-cache-dir . && chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
