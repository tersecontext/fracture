# CLAUDE.md — Lane D: Model Client

## Your Task
Create `src/fracture/model.py`. Unified LLM client for Claude API and OpenAI-compatible local endpoints. Read PLAN.md for API formats.

## Rules
- Async (httpx)
- Import ModelConfig from fracture.types
- `call()` returns raw text, `call_json()` parses JSON
- Strip markdown fences before JSON parse
- Provider selected from config.provider ("claude" or "local")

## Do NOT
- Import from other fracture modules besides types
- Hardcode API keys — read from config
