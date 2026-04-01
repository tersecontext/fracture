# Lane N: MCP Server

## File
`src/fracture/server.py`

## Depends On
ALL other lanes. This is the integration point.

## What to Build
An MCP server (using FastMCP) that exposes four tools: decompose, validate, further_decompose, feedback. Wires together all modules into the full pipeline.

## Interface

### Tool: decompose
```python
@server.tool()
async def decompose(task: str, project: str, dry_run: bool = False,
                    artifacts: list[dict] | None = None,
                    max_bead_hours: float = 3,
                    max_parallel_lanes: int = 4,
                    max_recursion_depth: int = 4) -> dict:
    """
    Full pipeline:
    1. analyzer.analyze(task, project, artifacts) → units
    2. dependency.derive_dependencies(units) → edges
    3. recursion.process(units, edges, project) → flat units, edges
    4. dependency.validate_graph(units, edges) → fix conflicts
    5. dependency.determine_phases(units, edges) → phases
    6. Check idempotency (no duplicate decomposition)
    7. If not dry_run:
       a. planner.generate_plans(units, edges, context) → plans
       b. instructor.generate_instructions(units, plans, context) → instructions
       c. beads.create_beads_transactional(all_bead_data) → bead_ids
    8. logger.log_decomposition(...)
    9. Return result
    """
```

### Tool: validate
```python
@server.tool()
async def validate(bead_ids: list[str]) -> dict:
    """
    1. For each bead_id: beads.show_bead(id) → parse FractureMetadata from notes
    2. Extract file manifests
    3. Run dependency.validate_graph() on the manifests
    4. Return conflicts and suggested dependency edges
    """
```

### Tool: further_decompose
```python
@server.tool()
async def further_decompose(bead_id: str, project: str, dry_run: bool = False) -> dict:
    """
    1. beads.show_bead(bead_id) → get current bead
    2. Parse description as the sub-task
    3. Run decompose pipeline on the sub-task
    4. If not dry_run:
       a. Close original bead with "decomposed into sub-beads" reason
       b. Create sub-beads with dependencies rewired
    5. Return sub-beads
    """
```

### Tool: feedback
```python
@server.tool()
async def feedback(bead_id: str, actual_creates: list[str],
                   actual_modifies: list[str]) -> dict:
    """
    Delegates to feedback_processor.process_feedback().
    Returns accuracy report.
    """
```

## Initialization
```python
def create_server(config_path: str = "fracture.yaml") -> FastMCP:
    config = load_config(config_path)
    tc_client = TerseContextClient(config.tersecontext_endpoint)
    model = ModelClient(config.model)
    analyzer = Analyzer(tc_client, model, config)
    planner = Planner(model)
    instructor = Instructor(model)
    recursion = RecursionEngine(analyzer, config)
    beads = BeadsClient(config.project_dir)
    logger = FractureLogger(config.log_dir, config.project_dir)
    feedback_proc = FeedbackProcessor(beads, logger)

    server = FastMCP("fracture")
    # Register tools with closures over the above instances
    return server
```

## Idempotency Check
Before creating beads, check for existing open beads with the same task hash:
```python
task_hash = hashlib.sha256(task.encode()).hexdigest()[:12]
existing = await beads.list_open_beads(decomposition_id=task_hash)
if existing:
    raise DecompositionError(f"Task already decomposed: {len(existing)} beads open")
```

## CLI Entry Point
```python
if __name__ == "__main__":
    server = create_server()
    server.run()  # stdio transport by default
```

## Completion Criteria
- All four MCP tools work end-to-end
- Full pipeline: task → TerseContext → analyze → dependencies → recurse → validate → plan → instruct → create beads → log
- Dry-run mode returns proposed beads without creating them
- Idempotency check prevents duplicate decompositions
- Transactional bead creation rolls back on failure
- Server starts and responds to MCP tool calls

## When Done
```bash
bd close <ID> "MCP server complete, all four tools working end-to-end"
```
