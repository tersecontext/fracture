# CLAUDE.md — Lane N: MCP Server

## Your Task
Create `src/fracture/server.py`. The MCP server that wires everything together. Read PLAN.md for the full pipeline.

## Rules
- Use FastMCP (from the `mcp` package / `fastmcp`)
- Import ALL other fracture modules
- Four tools: decompose, validate, further_decompose, feedback
- create_server() builds the full dependency graph of internal objects
- stdio transport by default

## Key Integration Points
- analyzer.analyze() → dependency.derive_dependencies() → recursion.process()
- dependency.validate_graph() → dependency.determine_phases()
- planner.generate_plans() → instructor.generate_instructions()
- beads.create_beads_transactional() → logger.log_decomposition()

## Do NOT
- Add business logic that belongs in other modules
- Duplicate validation logic — call the modules
- Skip the idempotency check
