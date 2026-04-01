# fracture

An MCP server that decomposes large tasks into dependency-ordered beads. It queries [TerseContext](https://github.com/tersecontext/tersecontext) for codebase intelligence, calls an LLM to reason about how to split the work, derives a dependency graph from write-set overlap, and creates the resulting tasks in [`bd`](https://github.com/tersecontext/beads).

Fracture does **not** execute beads, manage worktrees, or spawn agents. It only plans.

## How it works

```
task description
      │
      ▼
  TerseContext          ← semantic search, file tree, dependency graph
      │
      ▼
  LLM Call 1 (ANALYZE)  ← decompose into units with file manifests
      │
      ▼
  dependency graph      ← derived from write-set overlap, no LLM needed
      │
      ▼
  recursion             ← expand compound units recursively
      │
      ▼
  LLM Call 2 (PLAN)     ← generate per-unit implementation plans
      │
      ▼
  LLM Call 3 (INSTRUCT) ← generate per-unit CLAUDE.md agent instructions
      │
      ▼
  bd create             ← transactional bead creation with dependencies
```

Beads in the same phase have no write-set overlap and can run in parallel.

## Requirements

- Python 3.11+
- [`bd`](https://github.com/tersecontext/beads) CLI in PATH
- TerseContext running locally (default: `http://localhost:8000`)
- Anthropic API key, or a local OpenAI-compatible model endpoint

## Installation

```bash
pip install -e .
```

## Configuration

Copy `fracture.yaml` to your project root and edit as needed:

```yaml
tersecontext:
  endpoint: "http://localhost:8000"

beads:
  project_dir: "."

model:
  provider: "claude"          # or "local"
  claude:
    model: "claude-sonnet-4-20250514"
    api_key_env: "ANTHROPIC_API_KEY"
    max_tokens: 4096
  local:
    endpoint: "http://localhost:11434/v1"
    model: "qwen3.5"
    api_key: ""
    max_tokens: 4096

log:
  dir: ".fracture/logs"

defaults:
  max_bead_hours: 3           # split units estimated above this threshold
  max_parallel_lanes: 4       # max concurrent lanes per phase
  max_recursion_depth: 4      # max depth for compound unit expansion
  max_correction_rounds: 2    # LLM correction attempts on invalid output
```

Fracture searches for `fracture.yaml` in the current directory, then `~/.fracture.yaml`.

Set the API key in your environment:

```bash
export ANTHROPIC_API_KEY=sk-...
```

## Running the MCP server

```bash
python -m fracture.server
```

Or via stdio (for MCP clients):

```bash
python src/fracture/server.py
```

Add to your MCP client config (e.g. Claude Desktop):

```json
{
  "mcpServers": {
    "fracture": {
      "command": "python",
      "args": ["/path/to/fracture/src/fracture/server.py"]
    }
  }
}
```

## MCP Tools

### `decompose`

Decompose a task description into dependency-ordered beads.

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `task` | `string` | required | Natural language description of the work |
| `project` | `string` | required | Project identifier for TerseContext queries |
| `dry_run` | `boolean` | `false` | Plan only — skip bead creation |
| `artifacts` | `list[dict]` | `null` | Optional prior artifacts to pass to the analyzer |
| `max_bead_hours` | `float` | `3` | Override max hours per bead |
| `max_parallel_lanes` | `integer` | `4` | Override max parallel lanes |
| `max_recursion_depth` | `integer` | `4` | Override max recursion depth |

**Returns:**

```json
{
  "decomposition_id": "a3f1b9c2d4e5",
  "dry_run": false,
  "unit_count": 6,
  "bead_ids": ["proj-abc", "proj-def", "..."],
  "phases": [
    { "phase_number": 1, "bead_ids": ["0", "1"] },
    { "phase_number": 2, "bead_ids": ["2", "3", "4"] }
  ],
  "conflicts": [],
  "units": [...],
  "edges": [...]
}
```

`bead_ids` is empty when `dry_run=true`. `conflicts` lists any write-set overlaps that could not be resolved into dependency edges.

---

### `validate`

Check an existing set of beads for missing dependency edges.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `bead_ids` | `list[string]` | Bead IDs to validate |

**Returns:**

```json
{
  "valid": false,
  "conflicts": [
    {
      "bead_a": "proj-abc",
      "bead_b": "proj-def",
      "shared_files": ["src/auth/session.py"]
    }
  ],
  "suggested_edges": [
    {
      "from_bead": "proj-abc",
      "to_bead": "proj-def",
      "shared_files": ["src/auth/session.py"],
      "reason": "write-set overlap requires dependency"
    }
  ]
}
```

---

### `further_decompose`

Break a single bead into sub-beads. Runs the full decompose pipeline on the bead's description, closes the original bead, and creates the sub-beads with rewired dependencies.

**Parameters:**

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `bead_id` | `string` | required | The bead to decompose |
| `project` | `string` | required | Project identifier for TerseContext queries |
| `dry_run` | `boolean` | `false` | Plan only — skip bead creation and closing |

**Returns:**

```json
{
  "parent_bead_id": "proj-abc",
  "decomposition_id": "b7c2d1e3f4a5",
  "dry_run": false,
  "sub_bead_ids": ["proj-ghi", "proj-jkl"],
  "unit_count": 2,
  "phases": [...],
  "conflicts": []
}
```

---

### `feedback`

Report the actual files created and modified when a bead was executed. Compares against the predicted file manifest and logs an accuracy score.

**Parameters:**

| Name | Type | Description |
|------|------|-------------|
| `bead_id` | `string` | The bead that was executed |
| `actual_creates` | `list[string]` | Files actually created |
| `actual_modifies` | `list[string]` | Files actually modified |

**Returns:**

```json
{
  "bead_id": "proj-abc",
  "predicted_creates": ["src/auth/session.py"],
  "predicted_modifies": ["src/auth/__init__.py"],
  "actual_creates": ["src/auth/session.py", "src/auth/tokens.py"],
  "actual_modifies": ["src/auth/__init__.py"],
  "accuracy": 0.75,
  "correct": ["src/auth/session.py", "src/auth/__init__.py"],
  "missed": [],
  "unexpected": ["src/auth/tokens.py"]
}
```

`accuracy` = `|correct| / |predicted ∪ actual|`

## Logs

All decompositions and feedback events are written as append-only JSONL to `.fracture/logs/` (configurable). Each file is named `YYYY-MM-DD-{decomposition_id}.jsonl`.

## Idempotency

`decompose` and `further_decompose` hash the task text and check for existing open beads with the same hash before creating new ones. Re-submitting the same task while its beads are still open returns an error instead of creating duplicates. `dry_run=true` bypasses this check.
