# Lane A: Core Types and Schemas

## File
`src/fracture/types.py`

## What to Build
All dataclass/pydantic models used across the system. This is the shared vocabulary — every other module imports from here.

## Types to Define

### Unit
```python
@dataclass
class FileManifest:
    creates: list[str]   # new files this unit will create
    modifies: list[str]  # existing files this unit will change
    reads: list[str]     # files this unit references but won't change

@dataclass
class Unit:
    title: str
    description: str
    deliverable: str
    file_manifest: FileManifest
    estimated_hours: float
    rationale: str
```

### Bead metadata (stored in --notes as JSON)
```python
@dataclass
class FractureMetadata:
    version: int = 1
    file_manifest: FileManifest
    phase: int
    parallel_with: list[str]       # bead IDs
    decomposition_id: str
    estimated_hours: float
```

### Dependency edge
```python
@dataclass
class DependencyEdge:
    from_unit: int    # index
    to_unit: int      # index
    shared_files: list[str]
    reason: str
```

### Phase
```python
@dataclass
class Phase:
    phase_number: int
    bead_ids: list[str]
    gate: str         # what to validate before next phase
```

### DecompositionResult
```python
@dataclass
class DecompositionResult:
    units: list[Unit]
    edges: list[DependencyEdge]
    phases: list[Phase]
    plans: list[str]         # plan_md per unit
    instructions: list[str]  # claude_md per unit
    decomposition_id: str
    model_used: str
    dry_run: bool
```

### TerseContext response types
```python
@dataclass
class CodeResult:
    path: str
    content: str
    score: float
    node_type: str   # file | function | class | module

@dataclass
class DependencyGraphEdge:
    from_path: str
    to_path: str
    edge_type: str   # imports | calls | extends | tests

@dataclass
class CodebaseContext:
    file_tree: list[str]
    search_results: list[CodeResult]
    dependency_edges: list[DependencyGraphEdge]
    architecture_summary: str
```

### Feedback
```python
@dataclass
class FeedbackResult:
    bead_id: str
    predicted_creates: list[str]
    predicted_modifies: list[str]
    actual_creates: list[str]
    actual_modifies: list[str]
    missed_files: list[str]
    false_predictions: list[str]
    accuracy: float
```

### Config
```python
@dataclass
class ModelConfig:
    provider: str          # "claude" or "local"
    claude_model: str
    claude_api_key_env: str
    local_endpoint: str
    local_model: str
    max_tokens: int

@dataclass
class FractureConfig:
    tersecontext_endpoint: str
    project_dir: str
    model: ModelConfig
    log_dir: str
    max_bead_hours: float
    max_parallel_lanes: int
    max_recursion_depth: int
    max_correction_rounds: int
```

## Serialization
- All types must be JSON serializable (for audit log and notes field)
- Include `to_json()` and `from_json()` class methods on each type
- FractureMetadata must serialize to the exact format the validate tool expects

## Completion Criteria
- All types defined with full field specs
- JSON serialization round-trips correctly
- Types importable from `fracture.types`

## When Done
```bash
bd close <ID> "All types defined, JSON serialization tested"
```
Unblocks: Lanes E, F, G, H, I, J, K, L (everything depends on types)
