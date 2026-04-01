# Fracture Containerization Design

**Date:** 2026-04-01
**Status:** Approved

## Overview

Containerize Fracture so its Redis consumer can reach Breakdown's internal Redis stream (`stream:breakdown-approved`) without exposing Redis on a host port.

## Approach

Fracture gets its own `docker-compose.yml` that joins Breakdown's Docker network (`breakdown_default`) as an external network. No changes to Breakdown's `docker-compose.yml` are required.

## Prerequisites

- `bd` must be installed on the host before running `docker compose up`. The default expected path is `~/go/bin/bd`. If installed elsewhere, set `BD_BIN=/path/to/bd` in the shell or a `.env` file before starting.
- `ANTHROPIC_API_KEY` must be exported in the host shell (or placed in a `.env` file) before running `docker compose up`. If missing, the container starts successfully but fails at the first LLM call with an authentication error — no message is lost (the consumer does not ack until processing completes), but the error will appear in logs.

## Files

Three new/changed files in the fracture repo:

1. **`Dockerfile`** — builds from `python:3.12-slim`, installs fracture and its dependencies, sets working dir to `/app`, entrypoint to `python -m fracture.consumer --config /app/fracture.yaml`.

2. **`docker-compose.yml`** — single `fracture` service:
   - Joins `breakdown_default` as an external network (gives access to `redis://redis:6379`)
   - Bind-mounts `.:/app` read-write (the container writes audit logs to `.fracture/logs/` and `bd` writes to `.beads/`)
   - Bind-mounts `${BD_BIN:-~/go/bin/bd}:/usr/local/bin/bd:ro` — path is configurable via `BD_BIN` env var
   - Adds `extra_hosts: host.docker.internal:host-gateway` (TerseContext on host port 8090)
   - Passes `ANTHROPIC_API_KEY` from host environment (name only, no value in compose file)
   - `restart: unless-stopped`

3. **`fracture.yaml`** — change `redis.url` from `redis://localhost:6379` to `redis://redis:6379`. This change is intentional and permanent; the container is the supported way to run the consumer. For host-based debugging, pass `--config` pointing to a local override file with `redis.url: redis://localhost:6379`.

## Networking

| Dependency | How reached |
|---|---|
| Breakdown Redis | `redis://redis:6379` via `breakdown_default` network |
| TerseContext | `http://host.docker.internal:8090` via `extra_hosts` |
| Anthropic API | Outbound HTTPS, no special config needed |

## `bd` Binary

Bind-mounted from the host (path controlled by `BD_BIN` env var, defaulting to `~/go/bin/bd`) to `/usr/local/bin/bd` (read-only). This avoids pinning a release version in the image and means `bd` updates on the host are immediately available to the container.

`beads.py` prepends `~/go/bin` (i.e. `/root/go/bin` in the container) to PATH before each subprocess call. This directory does not exist in the container, but the prepend is harmless — `/usr/local/bin` remains in PATH from the base image, so `bd` is found there. No code changes to `beads.py` are required.

Note: `bd` upgrades on the host take effect immediately on the next container message (no restart required). Coordinate `bd` upgrades with a consumer restart if the new version requires a `.beads` schema migration.

## `.beads` Database

The fracture project directory is bind-mounted to `/app`. The container's working directory is `/app`, so `project_dir: "."` in `fracture.yaml` resolves correctly and `bd` commands operate against the host `.beads` db. Whittler, running on the host, reads from the same db with no changes.

## Environment Variables

- `ANTHROPIC_API_KEY` — passed through from host shell; required when `model.provider: claude`.

## What Is Not Changed

- Breakdown's `docker-compose.yml` — no Redis port exposure needed.
- Whittler — reads from the same `.beads` db on the host filesystem; no changes required.
- `fracture.yaml` model, TerseContext, and defaults sections — unchanged.
- `consumer.py` and all other Python modules — no code changes needed.
