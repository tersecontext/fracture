# CLAUDE.md — Lane B: Config Parser

## Project
Fracture — task decomposition engine for beads.

## Your Task
Create `src/fracture/config.py`. Parse `fracture.yaml` into `FractureConfig`. Read PLAN.md for the full YAML format.

## Rules
- Use PyYAML for parsing
- Import FractureConfig and ModelConfig from fracture.types
- Single function: `load_config(path) -> FractureConfig`
- Expand env vars for API keys using os.environ

## Do NOT
- Make API calls
- Import from other fracture modules besides types
