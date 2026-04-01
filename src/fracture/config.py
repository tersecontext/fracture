"""config.py — Parse fracture.yaml into a FractureConfig object.

Search order for config file:
  1. Explicit path argument
  2. Project root (cwd/fracture.yaml)
  3. Home directory (~/.fracture.yaml)

Environment variable references in api_key_env are expanded at load time.
Missing fields receive defaults. Validation errors raise ValueError.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from fracture.types import FractureConfig, ModelConfig

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_TERSECONTEXT_ENDPOINT = "http://localhost:8000"
_DEFAULT_PROJECT_DIR = "."
_DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-20250514"
_DEFAULT_CLAUDE_API_KEY_ENV = "ANTHROPIC_API_KEY"
_DEFAULT_LOCAL_ENDPOINT = "http://localhost:11434/v1"
_DEFAULT_LOCAL_MODEL = "qwen3.5"
_DEFAULT_MAX_TOKENS = 4096
_DEFAULT_LOG_DIR = ".fracture/logs"
_DEFAULT_MAX_BEAD_HOURS = 3.0
_DEFAULT_MAX_PARALLEL_LANES = 4
_DEFAULT_MAX_RECURSION_DEPTH = 4
_DEFAULT_MAX_CORRECTION_ROUNDS = 2


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_config_file(path: str) -> Path:
    """Return the resolved path to the config file.

    Raises FileNotFoundError if none of the search locations contain a file.
    """
    explicit = Path(path)
    cwd_default = Path.cwd() / "fracture.yaml"

    # Only add the explicit path as a separate candidate when it differs from
    # the cwd default (i.e. the caller passed an absolute path or a non-default
    # relative name).  This avoids checking the same path twice when the
    # default argument "fracture.yaml" is used.
    candidates: list[Path] = []
    if explicit.is_absolute() or explicit != Path("fracture.yaml"):
        candidates.append(explicit)
    candidates.append(cwd_default)
    candidates.append(Path.home() / ".fracture.yaml")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        f"fracture.yaml not found. Searched: {', '.join(str(c) for c in candidates)}"
    )


def _get(d: dict, *keys: str, default: Any = None) -> Any:
    """Traverse nested dict by key path, returning default if any key is missing."""
    cur = d
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key, None)
        if cur is None:
            return default
    return cur


def _parse_model(data: dict) -> ModelConfig:
    """Build a ModelConfig from the raw YAML dict, applying defaults."""
    provider: str = _get(data, "model", "provider", default="claude")

    claude_section = _get(data, "model", "claude", default={}) or {}
    local_section = _get(data, "model", "local", default={}) or {}

    claude_model: str = claude_section.get("model", _DEFAULT_CLAUDE_MODEL)
    # Stores the env var NAME, not the value; model.py resolves the actual key
    # at call time via os.environ[config.model.claude_api_key_env].
    claude_api_key_env: str = claude_section.get("api_key_env", _DEFAULT_CLAUDE_API_KEY_ENV)

    # max_tokens: use provider-specific section, fall back to the other, then default
    if provider == "claude":
        max_tokens: int = int(claude_section.get("max_tokens", _DEFAULT_MAX_TOKENS))
    else:
        max_tokens = int(local_section.get("max_tokens", _DEFAULT_MAX_TOKENS))

    local_endpoint: str = local_section.get("endpoint", _DEFAULT_LOCAL_ENDPOINT)
    local_model: str = local_section.get("model", _DEFAULT_LOCAL_MODEL)

    return ModelConfig(
        provider=provider,
        claude_model=claude_model,
        claude_api_key_env=claude_api_key_env,
        local_endpoint=local_endpoint,
        local_model=local_model,
        local_api_key=local_section.get("api_key", ""),
        max_tokens=max_tokens,
    )


def _validate(config: FractureConfig) -> None:
    """Raise ValueError for invalid configurations."""
    if config.model.provider == "claude":
        env_var = config.model.claude_api_key_env
        if not os.environ.get(env_var):
            raise ValueError(
                f"Provider is 'claude' but environment variable '{env_var}' is not set. "
                "Set the variable or switch to a local provider."
            )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_config(path: str = "fracture.yaml") -> FractureConfig:
    """Parse a fracture.yaml file into a FractureConfig.

    Args:
        path: Path to the config file. Falls back to project root and home
              directory if the explicit path is not found.

    Returns:
        A fully populated FractureConfig with defaults applied and
        environment variables expanded.

    Raises:
        FileNotFoundError: If no config file is found in any search location.
        ValueError: If the config is invalid (e.g. missing required API key).
        yaml.YAMLError: If the file contains invalid YAML.
    """
    config_path = _find_config_file(path)

    with config_path.open("r", encoding="utf-8") as fh:
        raw: dict = yaml.safe_load(fh) or {}

    # TerseContext
    tersecontext_endpoint: str = _get(
        raw, "tersecontext", "endpoint", default=_DEFAULT_TERSECONTEXT_ENDPOINT
    )

    # Beads / project directory
    project_dir: str = _get(raw, "beads", "project_dir", default=_DEFAULT_PROJECT_DIR)

    # Model
    model = _parse_model(raw)

    # Log directory
    log_dir: str = _get(raw, "log", "dir", default=_DEFAULT_LOG_DIR)

    # Defaults section
    defaults_section = raw.get("defaults") or {}
    max_bead_hours: float = float(
        defaults_section.get("max_bead_hours", _DEFAULT_MAX_BEAD_HOURS)
    )
    max_parallel_lanes: int = int(
        defaults_section.get("max_parallel_lanes", _DEFAULT_MAX_PARALLEL_LANES)
    )
    max_recursion_depth: int = int(
        defaults_section.get("max_recursion_depth", _DEFAULT_MAX_RECURSION_DEPTH)
    )
    max_correction_rounds: int = int(
        defaults_section.get("max_correction_rounds", _DEFAULT_MAX_CORRECTION_ROUNDS)
    )

    config = FractureConfig(
        tersecontext_endpoint=tersecontext_endpoint,
        project_dir=project_dir,
        model=model,
        log_dir=log_dir,
        max_bead_hours=max_bead_hours,
        max_parallel_lanes=max_parallel_lanes,
        max_recursion_depth=max_recursion_depth,
        max_correction_rounds=max_correction_rounds,
    )

    _validate(config)
    return config
