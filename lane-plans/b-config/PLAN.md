# Lane B: Config Parser

## File
`src/fracture/config.py`

## What to Build
Parse `fracture.yaml` into a `FractureConfig` object. Handle defaults, environment variable expansion for API keys, and validation.

## Config File Format
```yaml
tersecontext:
  endpoint: "http://localhost:8000"
beads:
  project_dir: "/path/to/project"
model:
  provider: "claude"
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
  max_bead_hours: 3
  max_parallel_lanes: 4
  max_recursion_depth: 4
  max_correction_rounds: 2
```

## Functions
- `load_config(path: str = "fracture.yaml") -> FractureConfig`
- Search order: explicit path, project root, home directory
- Expand `api_key_env` to actual value from environment
- Apply defaults for any missing field
- Validate: error if provider is "claude" but API key env is unset

## Completion Criteria
- Parses valid YAML into FractureConfig
- Applies defaults for missing fields
- Expands environment variable references
- Errors clearly on invalid config

## When Done
```bash
bd close <ID> "Config parser complete, defaults and validation working"
```
Unblocks: Lane N (server needs config)
