# Lane D: Model Client

## File
`src/fracture/model.py`

## What to Build
A unified LLM client that supports Claude API and any OpenAI-compatible local endpoint (Ollama, vLLM, TGI). All other modules call this — no direct API calls elsewhere.

## Interface

```python
class ModelClient:
    def __init__(self, config: ModelConfig):
        """Initialize with provider config."""

    async def call(self, system_prompt: str, user_message: str) -> str:
        """Send a prompt, return the raw text response."""

    async def call_json(self, system_prompt: str, user_message: str) -> dict:
        """Send a prompt, parse response as JSON. Strip markdown fences if present.
        Raises JsonParseError if response is not valid JSON."""
```

## Claude API Format
```python
POST https://api.anthropic.com/v1/messages
Headers: x-api-key, anthropic-version: "2023-06-01", content-type
Body: {
    "model": config.claude_model,
    "max_tokens": config.max_tokens,
    "system": system_prompt,
    "messages": [{"role": "user", "content": user_message}]
}
Response: data["content"][0]["text"]
```

## Local LLM Format (OpenAI-compatible)
```python
POST {config.local_endpoint}/chat/completions
Headers: content-type, Authorization (if api_key set)
Body: {
    "model": config.local_model,
    "messages": [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message}
    ],
    "response_format": {"type": "json_object"},
    "max_tokens": config.max_tokens
}
Response: data["choices"][0]["message"]["content"]
```

## JSON Parsing
- Strip ```json and ``` fences before parsing
- Strip any leading/trailing whitespace
- On parse failure, raise `JsonParseError(raw_response=raw)`

## Completion Criteria
- Claude API calls work with valid API key
- Local LLM calls work against Ollama endpoint
- call_json() reliably parses JSON from both providers
- Clean error messages on auth failure, connection failure, parse failure

## When Done
```bash
bd close <ID> "Model client complete, both providers tested"
```
Unblocks: Lanes G, H, I (all need model calls)
