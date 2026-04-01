"""types.py — Shared data types for Fracture.

Every other module imports from here. No business logic, no API calls,
no imports from other fracture modules.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_json(obj: Any) -> str:
    """Serialize a dataclass to a JSON string."""
    return json.dumps(asdict(obj))


def _from_dict(cls, data: dict) -> Any:
    """Recursively reconstruct a dataclass from a plain dict."""
    # Handled per-class via explicit from_json implementations.
    raise NotImplementedError


# ---------------------------------------------------------------------------
# File manifest
# ---------------------------------------------------------------------------

@dataclass
class FileManifest:
    creates: list[str]    # new files this unit will create
    modifies: list[str]   # existing files this unit will change
    reads: list[str]      # files this unit references but won't change

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str | dict) -> "FileManifest":
        d: dict = json.loads(data) if isinstance(data, str) else data
        return cls(
            creates=d.get("creates", []),
            modifies=d.get("modifies", []),
            reads=d.get("reads", []),
        )


# ---------------------------------------------------------------------------
# Unit
# ---------------------------------------------------------------------------

@dataclass
class Unit:
    title: str
    description: str
    deliverable: str
    file_manifest: FileManifest
    estimated_hours: float
    rationale: str

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str | dict) -> "Unit":
        d: dict = json.loads(data) if isinstance(data, str) else data
        return cls(
            title=d["title"],
            description=d["description"],
            deliverable=d["deliverable"],
            file_manifest=FileManifest.from_json(d["file_manifest"]),
            estimated_hours=float(d["estimated_hours"]),
            rationale=d["rationale"],
        )


# ---------------------------------------------------------------------------
# Bead metadata (stored in --notes as JSON)
# ---------------------------------------------------------------------------

@dataclass
class FractureMetadata:
    file_manifest: FileManifest
    phase: int
    parallel_with: list[str]    # bead IDs
    decomposition_id: str
    estimated_hours: float
    version: int = 1

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str | dict) -> "FractureMetadata":
        d: dict = json.loads(data) if isinstance(data, str) else data
        return cls(
            version=int(d.get("version", 1)),
            file_manifest=FileManifest.from_json(d["file_manifest"]),
            phase=int(d["phase"]),
            parallel_with=d.get("parallel_with", []),
            decomposition_id=d["decomposition_id"],
            estimated_hours=float(d["estimated_hours"]),
        )


# ---------------------------------------------------------------------------
# Dependency edge
# ---------------------------------------------------------------------------

@dataclass
class DependencyEdge:
    from_unit: int          # index into units list
    to_unit: int            # index into units list
    shared_files: list[str]
    reason: str

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str | dict) -> "DependencyEdge":
        d: dict = json.loads(data) if isinstance(data, str) else data
        return cls(
            from_unit=int(d["from_unit"]),
            to_unit=int(d["to_unit"]),
            shared_files=d.get("shared_files", []),
            reason=d["reason"],
        )


# ---------------------------------------------------------------------------
# Phase
# ---------------------------------------------------------------------------

@dataclass
class Phase:
    phase_number: int
    bead_ids: list[str]
    gate: str               # what to validate before next phase

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str | dict) -> "Phase":
        d: dict = json.loads(data) if isinstance(data, str) else data
        return cls(
            phase_number=int(d["phase_number"]),
            bead_ids=d.get("bead_ids", []),
            gate=d["gate"],
        )


# ---------------------------------------------------------------------------
# DecompositionResult
# ---------------------------------------------------------------------------

@dataclass
class DecompositionResult:
    units: list[Unit]
    edges: list[DependencyEdge]
    phases: list[Phase]
    plans: list[str]            # plan_md per unit
    instructions: list[str]     # claude_md per unit
    decomposition_id: str
    model_used: str
    dry_run: bool

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str | dict) -> "DecompositionResult":
        d: dict = json.loads(data) if isinstance(data, str) else data
        return cls(
            units=[Unit.from_json(u) for u in d.get("units", [])],
            edges=[DependencyEdge.from_json(e) for e in d.get("edges", [])],
            phases=[Phase.from_json(p) for p in d.get("phases", [])],
            plans=d.get("plans", []),
            instructions=d.get("instructions", []),
            decomposition_id=d["decomposition_id"],
            model_used=d["model_used"],
            dry_run=bool(d["dry_run"]),
        )


# ---------------------------------------------------------------------------
# TerseContext response types
# ---------------------------------------------------------------------------

@dataclass
class CodeResult:
    path: str
    content: str
    score: float
    node_type: str      # file | function | class | module

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str | dict) -> "CodeResult":
        d: dict = json.loads(data) if isinstance(data, str) else data
        return cls(
            path=d["path"],
            content=d["content"],
            score=float(d["score"]),
            node_type=d["node_type"],
        )


@dataclass
class DependencyGraphEdge:
    from_path: str
    to_path: str
    edge_type: str      # imports | calls | extends | tests

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str | dict) -> "DependencyGraphEdge":
        d: dict = json.loads(data) if isinstance(data, str) else data
        return cls(
            from_path=d["from_path"],
            to_path=d["to_path"],
            edge_type=d["edge_type"],
        )


@dataclass
class CodebaseContext:
    file_tree: list[str]
    search_results: list[CodeResult]
    dependency_edges: list[DependencyGraphEdge]
    architecture_summary: str

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str | dict) -> "CodebaseContext":
        d: dict = json.loads(data) if isinstance(data, str) else data
        return cls(
            file_tree=d.get("file_tree", []),
            search_results=[CodeResult.from_json(r) for r in d.get("search_results", [])],
            dependency_edges=[DependencyGraphEdge.from_json(e) for e in d.get("dependency_edges", [])],
            architecture_summary=d.get("architecture_summary", ""),
        )


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

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

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str | dict) -> "FeedbackResult":
        d: dict = json.loads(data) if isinstance(data, str) else data
        return cls(
            bead_id=d["bead_id"],
            predicted_creates=d.get("predicted_creates", []),
            predicted_modifies=d.get("predicted_modifies", []),
            actual_creates=d.get("actual_creates", []),
            actual_modifies=d.get("actual_modifies", []),
            missed_files=d.get("missed_files", []),
            false_predictions=d.get("false_predictions", []),
            accuracy=float(d["accuracy"]),
        )


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class ModelConfig:
    provider: str               # "claude", "claude-cli", or "local"
    claude_model: str
    claude_api_key_env: str
    local_endpoint: str
    local_model: str
    max_tokens: int
    local_api_key: str = ""
    claude_cli_path: str = "claude"  # path to claude CLI binary (claude-cli provider)

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str | dict) -> "ModelConfig":
        d: dict = json.loads(data) if isinstance(data, str) else data
        return cls(
            provider=d["provider"],
            claude_model=d["claude_model"],
            claude_api_key_env=d["claude_api_key_env"],
            local_endpoint=d["local_endpoint"],
            local_model=d["local_model"],
            max_tokens=int(d["max_tokens"]),
            local_api_key=d.get("local_api_key", ""),
            claude_cli_path=d.get("claude_cli_path", "claude"),
        )


@dataclass
class RedisConfig:
    url: str
    input_stream: str
    output_stream: str       # empty string = don't publish results
    consumer_group: str
    consumer_name: str
    block_ms: int = 5000

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str | dict) -> "RedisConfig":
        d: dict = json.loads(data) if isinstance(data, str) else data
        return cls(
            url=d["url"],
            input_stream=d["input_stream"],
            output_stream=d.get("output_stream", ""),
            consumer_group=d["consumer_group"],
            consumer_name=d["consumer_name"],
            block_ms=int(d.get("block_ms", 5000)),
        )


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
    redis: RedisConfig | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @classmethod
    def from_json(cls, data: str | dict) -> "FractureConfig":
        d: dict = json.loads(data) if isinstance(data, str) else data
        redis_data = d.get("redis")
        return cls(
            tersecontext_endpoint=d["tersecontext_endpoint"],
            project_dir=d["project_dir"],
            model=ModelConfig.from_json(d["model"]),
            log_dir=d["log_dir"],
            max_bead_hours=float(d["max_bead_hours"]),
            max_parallel_lanes=int(d["max_parallel_lanes"]),
            max_recursion_depth=int(d["max_recursion_depth"]),
            max_correction_rounds=int(d["max_correction_rounds"]),
            redis=RedisConfig.from_json(redis_data) if redis_data is not None else None,
        )
