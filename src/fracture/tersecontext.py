"""tersecontext.py — Async HTTP client for TerseContext codebase intelligence.

Calls POST /query and returns the plain-text context document.
Falls back gracefully when TerseContext is unavailable.

Do NOT import from other fracture modules besides types.
Do NOT make LLM calls — this is a data client only.
"""

from __future__ import annotations

import httpx

from fracture.types import CodebaseContext


class TerseContextClient:
    """Async HTTP client for TerseContext codebase intelligence queries."""

    def __init__(self, endpoint: str) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._available: bool | None = None

    async def get_context(self, task: str, project: str) -> CodebaseContext:
        """Query TerseContext and return the plain-text context document.

        Calls POST /query with the task as the question and project as the repo.
        Returns a CodebaseContext with the response text in architecture_summary.
        Returns an empty context if TerseContext is unavailable or the call fails.
        """
        if self._available is None:
            await self._check_available()
        if not self.is_available():
            return _empty_context()

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    self._endpoint + "/query",
                    json={
                        "repo": project,
                        "question": task,
                        "options": {"max_tokens": 2000},
                    },
                )
                response.raise_for_status()
                self._available = True
                return CodebaseContext(
                    file_tree=[],
                    search_results=[],
                    dependency_edges=[],
                    architecture_summary=response.text,
                )
        except Exception:
            return _empty_context()

    def is_available(self) -> bool:
        """Return cached availability status. False if never checked."""
        return bool(self._available)

    async def _check_available(self) -> bool:
        """Ping /health and cache the result."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(self._endpoint + "/health")
                self._available = response.status_code < 500
        except Exception:
            self._available = False
        return bool(self._available)


def _empty_context() -> CodebaseContext:
    return CodebaseContext(
        file_tree=[],
        search_results=[],
        dependency_edges=[],
        architecture_summary="",
    )
