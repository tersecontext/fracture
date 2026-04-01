# Fracture Containerization Design

**Date:** 2026-04-01
**Status:** Approved

## Overview

Containerize Fracture so its Redis consumer can reach Breakdown's internal Redis stream (`stream:breakdown-approved`) without exposing Redis on a host port.

## Approach

Fracture gets its own `docker-compose.yml` that joins Breakdown's Docker network as an external network. No changes to Breakdown's `docker-compose.yml` are required.

## Prerequisites

- `bd` must be installed on the host before running `docker compose up`. The default expected path is `$HOME/go/bin/bd`. If installed elsewhere, set `BD_BIN=/path/to/bd` in the shell or a `.env` file before starting.
- `ANTHROPIC_API_KEY` must be exported in the host shell (or placed in a `.env` file) before running `docker compose up`. If missing, `config.py` raises `ValueError` at startup and the container crashes before reading any messages. Ensure the key is set before starting.
- Breakdown must be running before starting Fracture. Confirm the Docker network name with `docker network ls` after starting Breakdown — the default is `breakdown_default` (derived from the compose project name). Update the `networks:` block in `docker-compose.yml` if it differs.

## Files

Three new/changed files in the fracture repo:

1. **`Dockerfile`** — builds from `python:3.12-slim`, installs fracture via `pip install .` (not `-e`), sets `WORKDIR /app` (required — `project_dir: "."` in `fracture.yaml` resolves relative to the working directory at runtime; `BeadsClient` passes it as `cwd` to every `bd` subprocess call), entrypoint `python -m fracture.consumer --config /app/fracture.yaml`. `fracture.yaml` is not baked into the image — it is expected at `/app/fracture.yaml` via the bind-mount at runtime. Running the image standalone without compose requires manually providing the config.

2. **`docker-compose.yml`** — single `fracture` service:
   ```yaml
   services:
     fracture:
       build: .
       volumes:
         - .:/app
         - ${BD_BIN:-${HOME}/go/bin/bd}:/usr/local/bin/bd:ro
       environment:
         - ANTHROPIC_API_KEY
       extra_hosts:
         - "host.docker.internal:host-gateway"
       networks:
         - breakdown
       restart: unless-stopped

   networks:
     breakdown:
       external: true
       name: breakdown_default
   ```
   - `.:/app` is read-write — the container writes audit logs to `.fracture/logs/` and `bd` writes to `.beads/`
   - `${BD_BIN:-${HOME}/go/bin/bd}` uses shell variable expansion (supported by Compose); `~` is not used because Compose does not expand tilde in bind-mount paths. `HOME` must be set in the environment Compose is launched from (it normally is on Linux). If the resolved path does not exist on the host, Docker will create an empty directory at that path instead of mounting a file — `bd` will be missing inside the container. Set `BD_BIN` explicitly if the default path is wrong.
   - The container runs as root (default for `python:3.12-slim`); the bind-mounted host directory must be writable by uid 0

3. **`fracture.yaml`** — change `redis.url` from `redis://localhost:6379` to `redis://redis:6379`. This is intentional and permanent; the container is the supported way to run the consumer. For host-based debugging, pass `--config` pointing to a separate override file with `redis.url: redis://localhost:6379`.

## Networking

| Dependency | How reached |
|---|---|
| Breakdown Redis | `redis://redis:6379` via `breakdown_default` network |
| TerseContext | `http://host.docker.internal:8090` via `extra_hosts` |
| Anthropic API | Outbound HTTPS, no special config needed |

## `bd` Binary

Bind-mounted from the host (path controlled by `BD_BIN` env var, defaulting to `$HOME/go/bin/bd`) to `/usr/local/bin/bd` (read-only). This avoids pinning a release version in the image and means `bd` updates on the host are immediately available to the container.

`beads.py` prepends `$HOME/go/bin` (resolves to `/root/go/bin` in the container) to PATH before each subprocess call. That directory does not exist in the container, but the prepend is harmless — `/usr/local/bin` remains in PATH from the base image, so `bd` is found there. No code changes to `beads.py` are required.

`bd` upgrades on the host take effect on the next message processed. Coordinate upgrades with a container restart if the new version requires a `.beads` schema migration.

## `.beads` Database

The fracture project directory is bind-mounted to `/app`. The container's working directory is `/app`, so `project_dir: "."` in `fracture.yaml` resolves correctly and `bd` commands operate against the host `.beads` db. Whittler, running on the host, reads from the same db with no changes required.

## Environment Variables

- `ANTHROPIC_API_KEY` — passed through from host shell; required when `model.provider: claude`.
- `BD_BIN` — optional; overrides the path to the `bd` binary on the host. Defaults to `$HOME/go/bin/bd`.

## Operational Notes

- **`stream:fracture-results`**: Fracture writes decomposition results and errors to this stream on Breakdown's Redis. Nothing currently consumes it; it will grow unbounded. This is acceptable for now — Redis streams are compact and can be trimmed manually if needed (`XTRIM stream:fracture-results MAXLEN 1000`).
- **Pending messages on hard kill**: The consumer acks in a `finally` block, so a clean shutdown (SIGINT/SIGTERM) will not leave messages in the PEL. A hard kill (SIGKILL, OOM) before `finally` runs will leave the in-flight message unacked. To recover, use `XAUTOCLAIM` or `XACK` manually against Breakdown's Redis.

## What Is Not Changed

- Breakdown's `docker-compose.yml` — no Redis port exposure needed.
- Whittler — reads from the same `.beads` db on the host filesystem; no changes required.
- `fracture.yaml` model, TerseContext, and defaults sections — unchanged.
- `consumer.py` and all other Python modules — no code changes needed.
