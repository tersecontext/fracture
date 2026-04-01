# Fracture Usage Guide

## Prerequisites

- Python 3.11+
- `bd` CLI installed and in PATH (`~/go/bin/bd` if installed via Go)
- TerseContext running (optional but recommended — Fracture degrades gracefully without it)
- Anthropic API key, or a local model running at an OpenAI-compatible endpoint

---

## 1. Install

```bash
git clone https://github.com/tersecontext/fracture
cd fracture
pip install -e .
```

---

## 2. Configure

Copy the example config to your project root:

```bash
cp /path/to/fracture/fracture.yaml ./fracture.yaml
```

Edit as needed:

```yaml
tersecontext:
  endpoint: "http://localhost:8000"   # set to "" to disable

beads:
  project_dir: "."                    # root where bd will find .beads/

model:
  provider: "claude"                  # "claude" or "local"
  claude:
    model: "claude-sonnet-4-20250514"
    api_key_env: "ANTHROPIC_API_KEY"  # name of the env var — not the key itself
    max_tokens: 4096
  local:
    endpoint: "http://localhost:11434/v1"
    model: "qwen3.5"
    api_key: ""
    max_tokens: 4096

log:
  dir: ".fracture/logs"

defaults:
  max_bead_hours: 3         # units estimated above this get split recursively
  max_parallel_lanes: 4
  max_recursion_depth: 4
  max_correction_rounds: 2
```

Set your API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Make sure `bd` is initialised in your project:

```bash
bd init
```

---

## 3. Start Fracture

There are two ways to run Fracture depending on how tasks arrive.

### Option A: MCP server (Claude Desktop / Claude Code)

```bash
python src/fracture/server.py
```

Starts the MCP server on stdio. Designed to be driven by an MCP client — not called directly from a terminal.

### Add to Claude Desktop

```json
{
  "mcpServers": {
    "fracture": {
      "command": "python",
      "args": ["/absolute/path/to/fracture/src/fracture/server.py"],
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

### Add to Claude Code

In `.claude/settings.json` in your project:

```json
{
  "mcpServers": {
    "fracture": {
      "command": "python",
      "args": ["/absolute/path/to/fracture/src/fracture/server.py"]
    }
  }
}
```

### Option B: Redis Stream consumer (Breakdown integration)

If you are running [Breakdown](https://github.com/tersecontext/breakdown), Fracture can consume approved tasks automatically. Add the `redis` section to `fracture.yaml`:

```yaml
redis:
  url: "redis://localhost:6379"
  input_stream: "stream:breakdown-approved"
  output_stream: "stream:fracture-results"
  consumer_group: "fracture"
  consumer_name: ""          # defaults to hostname
  block_ms: 5000
```

Then run:

```bash
python src/fracture/consumer.py --config fracture.yaml
```

The consumer runs until SIGINT/SIGTERM. Each approved task from Breakdown is automatically decomposed and beads are created. Results (bead IDs, phases, any conflicts) are published to `stream:fracture-results`.

**Message flow:**

```
Breakdown (approve task)
  → stream:breakdown-approved
    → Fracture consumer
      → decompose pipeline
        → bd (beads created)
      → stream:fracture-results
```

**What comes in from Breakdown:**

| Field | Maps to |
|-------|---------|
| `description` | `task` |
| `repo` | `project` |
| `research.affected_code[]` | `artifacts` (file hints for the analyzer) |

**What goes out to `stream:fracture-results`:**

```json
{
  "task_id": "uuid from Breakdown",
  "decomposition_id": "sha256 hash",
  "bead_ids": "[\"proj-abc\", \"proj-def\"]",
  "unit_count": "4",
  "phases": "[{\"phase_number\": 1, ...}]",
  "conflicts": "[]",
  "status": "ok"
}
```

On failure: `{"task_id": "...", "status": "error", "error": "message"}`.

---

## 4. Basic workflow

### Decompose a task

Ask your MCP client to call `decompose`:

```
decompose(
  task = "Add JWT authentication to the API — login endpoint, token refresh, and middleware guard on all /api routes",
  project = "myapp"
)
```

Fracture will:
1. Query TerseContext for relevant code in `myapp`
2. Ask the LLM to split the work into atomic units, each scoped to a specific set of files
3. Derive a dependency graph from write-set overlap (no LLM guessing)
4. Expand any units that are too large
5. Generate a per-unit implementation plan and agent instructions
6. Create beads in `bd` with all dependencies wired

You get back a decomposition ID, a list of bead IDs, and which beads can run in parallel:

```json
{
  "decomposition_id": "a3f1b9c2d4e5",
  "unit_count": 4,
  "bead_ids": ["myapp-a1b", "myapp-c2d", "myapp-e3f", "myapp-g4h"],
  "phases": [
    { "phase_number": 1, "bead_ids": ["0"] },
    { "phase_number": 2, "bead_ids": ["1", "2"] },
    { "phase_number": 3, "bead_ids": ["3"] }
  ],
  "conflicts": []
}
```

Beads in the same phase have no write-set overlap — they can run in parallel agents without merge conflicts.

### Try it without creating beads

Use `dry_run=true` to see the decomposition plan before committing:

```
decompose(
  task = "Refactor the database layer to use connection pooling",
  project = "myapp",
  dry_run = true
)
```

Returns the same structure but `bead_ids` will be empty and nothing is written to `bd`.

---

## 5. Check existing beads for conflicts

If you have a set of beads that were created manually (not via Fracture), you can validate whether their dependency ordering is correct:

```
validate(
  bead_ids = ["myapp-a1b", "myapp-c2d", "myapp-e3f"]
)
```

Returns:

```json
{
  "valid": false,
  "conflicts": [
    {
      "bead_a": "myapp-a1b",
      "bead_b": "myapp-e3f",
      "shared_files": ["src/db/connection.py"]
    }
  ],
  "suggested_edges": [
    {
      "from_bead": "myapp-a1b",
      "to_bead": "myapp-e3f",
      "shared_files": ["src/db/connection.py"],
      "reason": "write-set overlap requires dependency"
    }
  ]
}
```

`valid: true` means the bead set has no unguarded write-set conflicts.

---

## 6. Break down a bead that's too large

If an agent claims a bead but finds it's too large to complete in one session:

```
further_decompose(
  bead_id = "myapp-c2d",
  project = "myapp"
)
```

Fracture will:
1. Read the bead's description
2. Run the full decompose pipeline on it
3. Close the original bead (`bd close myapp-c2d "decomposed into sub-beads"`)
4. Create sub-beads in its place with the original bead's dependencies rewired

Returns the new sub-bead IDs. Use `dry_run=true` to preview first.

---

## 7. Report what actually happened

After an agent completes a bead, report the actual files it touched:

```
feedback(
  bead_id = "myapp-a1b",
  actual_creates = ["src/auth/jwt.py", "src/auth/middleware.py"],
  actual_modifies = ["src/auth/__init__.py"]
)
```

Returns an accuracy report:

```json
{
  "bead_id": "myapp-a1b",
  "predicted_creates": ["src/auth/jwt.py"],
  "predicted_modifies": ["src/auth/__init__.py"],
  "actual_creates": ["src/auth/jwt.py", "src/auth/middleware.py"],
  "actual_modifies": ["src/auth/__init__.py"],
  "accuracy": 0.75,
  "correct": ["src/auth/jwt.py", "src/auth/__init__.py"],
  "missed": [],
  "unexpected": ["src/auth/middleware.py"]
}
```

`accuracy` is Jaccard similarity: `|correct| / |predicted ∪ actual|`. A score of 1.0 means the prediction was exact. This is logged to `.fracture/logs/` and can be used to tune decomposition quality over time.

---

## 8. Tips

**Write specific tasks.** Vague tasks produce vague units. "Add auth" is worse than "Add JWT login endpoint that issues access + refresh tokens and store sessions in Redis."

**Use dry_run before large decompositions.** Always worth a preview on tasks touching many files.

**TerseContext improves accuracy significantly.** Without it, Fracture falls back to the LLM's general knowledge of your codebase. With it, units get scoped to real file paths and the dependency graph is grounded in actual imports.

**Phase = safe parallelism.** All beads in the same phase can be claimed by different agents simultaneously without conflicts. Beads in different phases must be executed in order.

**further_decompose is safe to dry-run.** The original bead is not closed until `dry_run=false` is confirmed.

**Logs are in `.fracture/logs/`.** Each decomposition gets its own JSONL file named by date and decomposition ID. Useful for debugging or auditing what the LLM decided.
