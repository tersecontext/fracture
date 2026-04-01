"""prompts.py — Prompt builder functions for Fracture LLM calls.

Three functions return (system_prompt, user_message) tuples for each of
the three LLM call stages: ANALYZE, PLAN, and INSTRUCT.

No API calls are made here — only string assembly.
"""

from __future__ import annotations

from fracture.types import CodebaseContext, DependencyEdge, Unit


# ---------------------------------------------------------------------------
# System prompt constants
# ---------------------------------------------------------------------------

ANALYZE_SYSTEM_PROMPT = """\
You are a senior staff engineer decomposing a task into independent units
of work for parallel execution by AI coding agents.

You will receive:
1. A task description
2. Codebase context from a knowledge graph (file contents, dependency
   edges, call graphs)

Your job:
- Identify the distinct units of work needed to complete this task
- For each unit, predict exactly which files will be CREATED, MODIFIED,
  or READ
- Ensure units that modify the same file are marked as sequential
- Prefer splitting along file boundaries — two units that touch
  different files can run in parallel

CRITICAL RULES:
- A unit must have a single, concrete deliverable
- A unit must be completable by one agent in one session (under 3 hours)
- If a unit touches files in 3+ unrelated modules, split it further
- New files (creates) never conflict — only modifications to existing
  files cause conflicts
- Be precise about file paths. Use the exact paths from the codebase
  context provided.

Respond ONLY with valid JSON matching this schema:
{
  "units": [
    {
      "title": "string — short descriptive title",
      "description": "string — 2-3 sentences on what this unit does",
      "deliverable": "string — the single concrete output",
      "file_manifest": {
        "creates": ["string — exact file paths"],
        "modifies": ["string — exact file paths"],
        "reads": ["string — exact file paths"]
      },
      "estimated_hours": number,
      "rationale": "string — why this is a separate unit"
    }
  ],
  "sequencing_notes": "string — explain which units must be serial and why"
}"""

PLAN_SYSTEM_PROMPT = """\
You are writing detailed implementation plans for AI coding agents.
Each plan will be stored in a bead (task tracker) and read by an agent
that will execute the work independently.

You will receive a list of units of work with their file manifests and
dependency relationships. For each unit, write a plan document.

Each plan must include:
- What to build (specific, actionable)
- Why this is a separate unit (what files it touches, what it enables)
- The file manifest (creates/modifies/reads)
- Completion criteria (how the agent knows it's done)
- What this unit unblocks when complete
- Key context from the codebase (relevant code excerpts to reference)

Keep each plan under 150 lines. Be specific about file paths and
function names. Do not be generic.

Respond ONLY with valid JSON:
{
  "plans": [
    {
      "unit_index": number,
      "plan_md": "string — the full plan, markdown formatted"
    }
  ]
}"""

INSTRUCT_SYSTEM_PROMPT = """\
You are writing scoped agent instructions (CLAUDE.md files) for AI
coding agents. Each instruction set will be read by a single agent
working in an isolated git worktree.

The agent will ONLY see your instructions and the files in its worktree.
It will NOT see the other beads, the full codebase, or the overall plan.
Your instructions must be self-contained.

For each unit, write a CLAUDE.md that includes:
- Project context (1-2 sentences)
- What this specific task is
- Key files to read and modify (exact paths)
- Tech stack and constraints
- What NOT to do (prevent scope creep)
- Rules (single file, no localStorage, etc. — as appropriate)

Keep each instruction set under 50 lines. Be direct. No preamble.

Respond ONLY with valid JSON:
{
  "instructions": [
    {
      "unit_index": number,
      "claude_md": "string — the full CLAUDE.md content"
    }
  ]
}"""


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def build_analyze_prompt(task: str, context: CodebaseContext) -> tuple[str, str]:
    """Call 1: ANALYZE. Returns (system_prompt, user_message)."""
    parts: list[str] = []

    parts.append("## Task\n")
    parts.append(task)
    parts.append("")

    # File tree
    if context.file_tree:
        parts.append("## File Tree\n")
        for path in context.file_tree:
            parts.append(f"  {path}")
        parts.append("")

    # Code excerpts
    if context.search_results:
        parts.append("## Code Excerpts\n")
        for result in context.search_results:
            parts.append(f"--- {result.path} ---")
            parts.append(result.content)
            parts.append("")

    # Dependency edges
    if context.dependency_edges:
        parts.append("## Dependency Edges\n")
        for edge in context.dependency_edges:
            parts.append(f"{edge.from_path} → {edge.to_path} ({edge.edge_type})")
        parts.append("")

    # Codebase context from TerseContext
    if context.architecture_summary:
        parts.append("## Codebase Context\n")
        parts.append(context.architecture_summary)
        parts.append("")

    return ANALYZE_SYSTEM_PROMPT, "\n".join(parts)


def build_plan_prompt(
    units: list[Unit],
    edges: list[DependencyEdge],
    context: CodebaseContext,
) -> tuple[str, str]:
    """Call 2: PLAN. Returns (system_prompt, user_message)."""
    parts: list[str] = []

    # Units with manifests
    parts.append("## Units of Work\n")
    for i, unit in enumerate(units):
        parts.append(f"### Unit {i}: {unit.title}")
        parts.append(f"**Description:** {unit.description}")
        parts.append(f"**Deliverable:** {unit.deliverable}")
        parts.append(f"**Estimated hours:** {unit.estimated_hours}")
        parts.append(f"**Rationale:** {unit.rationale}")
        parts.append("**File manifest:**")
        fm = unit.file_manifest
        if fm.creates:
            parts.append(f"  creates: {', '.join(fm.creates)}")
        if fm.modifies:
            parts.append(f"  modifies: {', '.join(fm.modifies)}")
        if fm.reads:
            parts.append(f"  reads: {', '.join(fm.reads)}")
        parts.append("")

    # Dependency edges
    if edges:
        parts.append("## Dependency Edges\n")
        for edge in edges:
            shared = ", ".join(edge.shared_files) if edge.shared_files else "none"
            parts.append(
                f"Unit {edge.from_unit} → Unit {edge.to_unit} "
                f"(shared files: {shared}; reason: {edge.reason})"
            )
        parts.append("")

    # Codebase context from TerseContext
    if context.architecture_summary:
        parts.append("## Codebase Context\n")
        parts.append(context.architecture_summary)
        parts.append("")
    elif context.search_results:
        parts.append("## Relevant Code Excerpts\n")
        for result in context.search_results:
            parts.append(f"--- {result.path} ---")
            parts.append(result.content)
            parts.append("")

    return PLAN_SYSTEM_PROMPT, "\n".join(parts)


def build_instruct_prompt(
    units: list[Unit],
    plans: list[str],
    context: CodebaseContext,
) -> tuple[str, str]:
    """Call 3: INSTRUCT. Returns (system_prompt, user_message)."""
    parts: list[str] = []

    # Units with their plans
    parts.append("## Units and Plans\n")
    for i, unit in enumerate(units):
        parts.append(f"### Unit {i}: {unit.title}")
        parts.append(f"**Description:** {unit.description}")
        parts.append(f"**Deliverable:** {unit.deliverable}")
        fm = unit.file_manifest
        if fm.creates:
            parts.append(f"  creates: {', '.join(fm.creates)}")
        if fm.modifies:
            parts.append(f"  modifies: {', '.join(fm.modifies)}")
        if fm.reads:
            parts.append(f"  reads: {', '.join(fm.reads)}")
        if i < len(plans):
            parts.append(f"\n**Plan:**\n{plans[i]}")
        parts.append("")

    # Codebase context from TerseContext
    if context.architecture_summary:
        parts.append("## Codebase Context\n")
        parts.append(context.architecture_summary)
        parts.append("")
    elif context.search_results:
        parts.append("## Relevant Code Context\n")
        for result in context.search_results:
            parts.append(f"--- {result.path} ---")
            parts.append(result.content)
            parts.append("")

    return INSTRUCT_SYSTEM_PROMPT, "\n".join(parts)
