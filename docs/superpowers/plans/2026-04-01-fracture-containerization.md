# Fracture Containerization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `Dockerfile` and `docker-compose.yml` so Fracture's Redis consumer runs in a container that joins Breakdown's Docker network and reaches its internal Redis.

**Architecture:** Fracture gets its own compose file that declares `breakdown_default` as an external network. The fracture project directory is bind-mounted to `/app` (gives the container access to `fracture.yaml` and the `.beads` db). The `bd` binary is bind-mounted from the host. One line in `fracture.yaml` changes.

**Tech Stack:** Docker, Docker Compose v2, Python 3.12, `python:3.12-slim` base image.

---

## File Map

| Action | Path | Purpose |
|--------|------|---------|
| Create | `Dockerfile` | Build image: install fracture package, set WORKDIR, set entrypoint |
| Create | `docker-compose.yml` | Run container: network, volumes, env, extra_hosts |
| Modify | `fracture.yaml` | Change `redis.url` to `redis://redis:6379` |

No other files change.

---

### Task 1: Write the Dockerfile

**Files:**
- Create: `Dockerfile`

- [ ] **Step 1: Create `Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src/ src/

RUN pip install --no-cache-dir .

ENTRYPOINT ["python", "-m", "fracture.consumer", "--config", "/app/fracture.yaml"]
```

Key points:
- `WORKDIR /app` is required — `BeadsClient` uses `project_dir: "."` as `cwd` for every `bd` subprocess call; it must resolve to `/app` at runtime.
- `pip install .` (not `-e`) installs the package into site-packages. The bind-mount at runtime overlays `/app` with the host directory but does not affect the installed package.
- `fracture.yaml` is NOT copied into the image — it is provided by the `.:/app` bind-mount at runtime.

- [ ] **Step 2: Verify the image builds**

```bash
docker build -t fracture:local .
```

Expected: build succeeds with no errors. The final line should be something like `Successfully built <id>` or `=> exporting to image`.

If pip install fails, check that `pyproject.toml` and `src/` are present in the build context.

- [ ] **Step 3: Commit**

```bash
git add Dockerfile
git commit -m "feat: add Dockerfile for fracture consumer"
```

---

### Task 2: Write docker-compose.yml

**Files:**
- Create: `docker-compose.yml`

- [ ] **Step 1: Check Breakdown's actual Docker network name**

```bash
docker network ls | grep breakdown
```

Expected output contains a line like:

```
<id>   breakdown_default   bridge   local
```

If the name differs from `breakdown_default`, use the actual name in the `networks.breakdown.name` field below.

- [ ] **Step 2: Create `docker-compose.yml`**

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

Notes:
- `.:/app` is read-write intentionally — `bd` writes to `.beads/` and the consumer writes audit logs to `.fracture/logs/`.
- `${BD_BIN:-${HOME}/go/bin/bd}` — Docker Compose expands `${HOME}` from the host environment. Do NOT use `~` — Compose does not expand tilde in volume paths. If the bd binary is at a different path, set `BD_BIN=/path/to/bd` before running compose.
- `extra_hosts: host.docker.internal:host-gateway` — required on Linux to make `host.docker.internal` resolve to the host IP (used by `fracture.yaml`'s `tersecontext.endpoint`).
- If the network name from Step 1 differs from `breakdown_default`, update `name: breakdown_default` accordingly.

- [ ] **Step 3: Verify bd binary path resolves correctly on the host**

```bash
ls -la ${BD_BIN:-$HOME/go/bin/bd}
```

Expected: shows the `bd` file (not a directory). If this prints a directory listing or "No such file or directory", set `BD_BIN` to the correct path or install `bd` first.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add docker-compose.yml — joins breakdown network, mounts bd and .beads"
```

---

### Task 3: Update fracture.yaml

**Files:**
- Modify: `fracture.yaml`

- [ ] **Step 1: Change the redis URL**

In `fracture.yaml`, change:

```yaml
redis:
  url: "redis://localhost:6379"
```

to:

```yaml
redis:
  url: "redis://redis:6379"
```

Everything else in `fracture.yaml` stays the same.

- [ ] **Step 2: Commit**

```bash
git add fracture.yaml
git commit -m "config: point redis consumer at breakdown's internal redis (redis://redis:6379)"
```

---

### Task 4: Smoke test — bring up the container

**Files:** none

- [ ] **Step 1: Ensure prerequisites are met**

```bash
# API key set?
echo $ANTHROPIC_API_KEY | head -c 10

# bd binary exists?
ls -la ${BD_BIN:-$HOME/go/bin/bd}

# Breakdown is running and network exists?
docker network ls | grep breakdown
```

All three must succeed before proceeding.

- [ ] **Step 2: Start the container**

```bash
docker compose up --build
```

Expected log output within a few seconds:

```
fracture-fracture-1  | INFO fracture.consumer: Created consumer group fracture on stream:breakdown-approved
fracture-fracture-1  | INFO fracture.consumer: Fracture consumer started — listening on stream:breakdown-approved
```

Or if the consumer group already exists:

```
fracture-fracture-1  | INFO fracture.consumer: Consumer group fracture already exists
fracture-fracture-1  | INFO fracture.consumer: Fracture consumer started — listening on stream:breakdown-approved
```

If the container crashes immediately with `ValueError`, `ANTHROPIC_API_KEY` is not set.

If the container crashes with a network error (`Could not connect to Redis`), the breakdown network is not reachable — verify the network name with `docker network ls`.

If `bd` is not found (error like `FileNotFoundError: [Errno 2] No such file or directory: 'bd'`), the bind-mount resolved to a directory instead of a file — check the `BD_BIN` path.

- [ ] **Step 3: Send a test message and verify processing**

In a separate terminal, exec into the breakdown Redis container and push a test message:

```bash
# Find the Redis container
docker ps | grep redis

# Push a minimal test message
docker exec -it <breakdown-redis-container> redis-cli XADD stream:breakdown-approved '*' \
  task_id test-001 \
  description "Add a hello world endpoint" \
  repo fracture \
  research '{}'
```

Expected in Fracture logs:

```
INFO fracture.consumer: Processing task test-001: Add a hello world endpoint...
INFO fracture.consumer: Task test-001 decomposed: N beads, N phases
```

Or an error result written to `stream:fracture-results` if decomposition fails — check with:

```bash
docker exec -it <breakdown-redis-container> redis-cli XRANGE stream:fracture-results - +
```

- [ ] **Step 4: Stop and run detached**

```bash
# Stop foreground instance
Ctrl-C

# Run detached
docker compose up -d

# Verify running
docker compose ps
docker compose logs -f
```

- [ ] **Step 5: Commit**

```bash
# No code changes in this task — nothing to commit
# If you adjusted fracture.yaml or docker-compose.yml during debugging, commit those changes now
```
