"""tersecontext.py — Async HTTP client for TerseContext codebase intelligence.

Queries TerseContext for semantic search, dependency graphs, and file trees.
All network calls are async via httpx. Falls back gracefully when unavailable.

Do NOT import from other fracture modules besides types.
Do NOT make LLM calls — this is a data client only.
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from fracture.types import CodebaseContext, CodeResult, DependencyGraphEdge


# ---------------------------------------------------------------------------
# TerseContextClient
# ---------------------------------------------------------------------------


class TerseContextClient:
    """Async HTTP client for TerseContext codebase intelligence queries."""

    def __init__(self, endpoint: str) -> None:
        """Connect to TerseContext at the given endpoint.

        Args:
            endpoint: Base URL of the TerseContext server, e.g. "http://localhost:8080".
        """
        self._endpoint = endpoint.rstrip("/")
        self._available: bool | None = None  # cached after first health check

    # ------------------------------------------------------------------
    # Public query methods
    # ------------------------------------------------------------------

    async def semantic_search(
        self,
        query: str,
        project: str,
        max_results: int = 10,
    ) -> list[CodeResult]:
        """Find code relevant to a natural language query.

        Args:
            query: Natural language description of code to find.
            project: Project identifier passed to TerseContext.
            max_results: Maximum number of results to return.

        Returns:
            List of CodeResult objects sorted by relevance score, or empty list
            on failure.
        """
        payload: dict[str, Any] = {
            "query": query,
            "project": project,
            "max_results": max_results,
        }
        try:
            data = await self._post("/search", payload)
        except Exception:
            return []

        results: list[CodeResult] = []
        for item in data.get("results", []):
            try:
                results.append(
                    CodeResult(
                        path=item["path"],
                        content=item["content"],
                        score=float(item["score"]),
                        node_type=item["node_type"],
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
        return results

    async def dependency_graph(
        self,
        paths: list[str],
        project: str,
        depth: int = 2,
    ) -> list[DependencyGraphEdge]:
        """Get import/call/test edges for the given files.

        Args:
            paths: File paths whose dependency graph should be fetched.
            project: Project identifier passed to TerseContext.
            depth: How many hops of the dependency graph to traverse.

        Returns:
            List of DependencyGraphEdge objects, or empty list on failure.
        """
        if not paths:
            return []

        payload: dict[str, Any] = {
            "paths": paths,
            "project": project,
            "depth": depth,
        }
        try:
            data = await self._post("/graph", payload)
        except Exception:
            return []

        edges: list[DependencyGraphEdge] = []
        for item in data.get("edges", []):
            try:
                edges.append(
                    DependencyGraphEdge(
                        from_path=item["from"],
                        to_path=item["to"],
                        edge_type=item["type"],
                    )
                )
            except (KeyError, ValueError, TypeError):
                continue
        return edges

    async def file_tree(
        self,
        project: str,
        path_prefix: str = "",
    ) -> list[str]:
        """Get all file paths in the project.

        Args:
            project: Project identifier passed to TerseContext.
            path_prefix: Optional prefix to filter results.

        Returns:
            List of file path strings, or empty list on failure.
        """
        payload: dict[str, Any] = {
            "project": project,
            "path_prefix": path_prefix,
        }
        try:
            data = await self._post("/files", payload)
        except Exception:
            return []

        return [str(f) for f in data.get("files", [])]

    async def get_context(self, task: str, project: str) -> CodebaseContext:
        """High-level: extract topics from task, run searches, aggregate results.

        Extracts keywords from the task string, runs semantic_search for each
        keyword batch, collects the distinct file paths from results, calls
        dependency_graph on those paths, and fetches the full file_tree.

        Falls back to an empty CodebaseContext with is_available=False (indicated
        by architecture_summary) when TerseContext is unreachable.

        Args:
            task: Natural language description of the task to decompose.
            project: Project identifier passed to TerseContext.

        Returns:
            Aggregated CodebaseContext.
        """
        if self._available is None:
            await self._check_available()
        if not self.is_available():
            return _empty_context()

        # Extract meaningful keywords from the task string.
        keywords = _extract_keywords(task)

        # Run semantic searches — one broad search plus targeted keyword searches.
        search_results: list[CodeResult] = []
        seen_paths: set[str] = set()

        queries = [task] + [" ".join(keywords[i : i + 3]) for i in range(0, len(keywords), 3)]
        for query in queries:
            if not query.strip():
                continue
            try:
                results = await self.semantic_search(query, project, max_results=10)
            except Exception:
                results = []
            for result in results:
                if result.path not in seen_paths:
                    seen_paths.add(result.path)
                    search_results.append(result)

        # Fetch dependency graph for discovered paths.
        found_paths = list(seen_paths)
        try:
            dep_edges = await self.dependency_graph(found_paths, project)
        except Exception:
            dep_edges = []

        # Fetch full file tree.
        try:
            files = await self.file_tree(project)
        except Exception:
            files = []

        return CodebaseContext(
            file_tree=files,
            search_results=search_results,
            dependency_edges=dep_edges,
            architecture_summary="",
        )

    def is_available(self) -> bool:
        """Health check — is TerseContext reachable?

        Returns the cached result from the last connectivity attempt. Callers
        should trigger an async health check via _check_available() before
        relying on this value. Returns False if never checked.
        """
        return bool(self._available)

    async def _check_available(self) -> bool:
        """Perform an async connectivity check and cache the result."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(self._endpoint + "/", timeout=5.0)
                self._available = response.status_code < 500
        except Exception:
            self._available = False
        return bool(self._available)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST to the TerseContext API and return the parsed JSON response.

        Raises httpx.HTTPError or httpx.RequestError on failure so callers can
        catch and return empty results.
        """
        url = self._endpoint + path
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            result: dict[str, Any] = response.json()
            # Mark as available on a successful call.
            self._available = True
            return result


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _empty_context() -> CodebaseContext:
    """Return an empty CodebaseContext signalling TerseContext is unavailable."""
    return CodebaseContext(
        file_tree=[],
        search_results=[],
        dependency_edges=[],
        architecture_summary="",
    )


_STOP_WORDS: frozenset[str] = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "shall", "can", "need", "dare",
        "ought", "used", "it", "its", "this", "that", "these", "those",
        "i", "we", "you", "he", "she", "they", "what", "which", "who",
        "not", "no", "so", "if", "then", "than", "as", "into", "out",
        "up", "down", "about", "all", "also", "just", "more", "such",
    }
)


def _extract_keywords(text: str) -> list[str]:
    """Extract meaningful keywords from a task description.

    Strips punctuation, lowercases, removes stop words, and de-duplicates while
    preserving order.
    """
    tokens = re.split(r"[\s\W]+", text.lower())
    seen: set[str] = set()
    keywords: list[str] = []
    for token in tokens:
        if len(token) >= 3 and token not in _STOP_WORDS and token not in seen:
            seen.add(token)
            keywords.append(token)
    return keywords
