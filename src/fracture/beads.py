"""beads.py — bd CLI integration for Fracture.

This is the ONLY module that calls the bd CLI directly. All other modules that
need bd interaction must go through BeadsClient. Handles transactional bead
creation with rollback on failure.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_env() -> dict[str, str]:
    """Return an environment dict with ~/go/bin prepended to PATH."""
    env = os.environ.copy()
    go_bin = os.path.expanduser("~/go/bin")
    existing = env.get("PATH", "")
    env["PATH"] = f"{go_bin}:{existing}" if existing else go_bin
    return env


class BeadsError(Exception):
    """Raised when a bd CLI call fails."""


# ---------------------------------------------------------------------------
# BeadsClient
# ---------------------------------------------------------------------------

class BeadsClient:
    """Wrapper around the bd CLI.

    All subprocess calls use asyncio.create_subprocess_exec (never shell=True).
    The working directory for every call is set to self.project_dir so that bd
    can locate the .beads database via auto-discovery.
    """

    def __init__(self, project_dir: str) -> None:
        """Set working directory for bd commands.

        Args:
            project_dir: Absolute path to the project root that contains the
                         .beads database directory.
        """
        self.project_dir = project_dir
        self._env = _build_env()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run(self, *args: str, input_bytes: bytes | None = None) -> tuple[str, str]:
        """Run a bd command and return (stdout, stderr).

        Raises BeadsError if the process exits with a non-zero status.
        """
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.project_dir,
            env=self._env,
        )
        stdout_bytes, stderr_bytes = await proc.communicate(input=input_bytes)
        stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
        stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            raise BeadsError(
                f"bd command failed (exit {proc.returncode}): {' '.join(args)!r}\n"
                f"stderr: {stderr}\nstdout: {stdout}"
            )
        return stdout, stderr

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_bead(
        self,
        title: str,
        bead_type: str,
        priority: int,
        deps: list[str],
        description: str,
        design: str,
        acceptance: str,
        notes: str,
    ) -> str:
        """Create a bead via bd create. Returns the bead ID.

        Long content (description, design) is written to temporary files and
        passed via --body-file / --design-file to avoid shell-length limits and
        escaping issues. After the bead is created, each entry in *deps* is
        linked with ``bd dep add <new_id> --blocked-by <dep>`` so the new bead
        is blocked by its dependencies.

        Args:
            title:       Short title for the bead.
            bead_type:   bd issue type (task, feature, bug, …).
            priority:    Numeric priority (0 = highest).
            deps:        List of bead IDs that the new bead depends on.
            description: Long description text.
            design:      Design notes text.
            acceptance:  Acceptance criteria text.
            notes:       Additional notes (typically JSON-serialised metadata).

        Returns:
            The newly created bead ID string (e.g. ``"fracture-abc"``).
        """
        # Write long content to temp files so we avoid escaping / length issues.
        with (
            tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as desc_f,
            tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as design_f,
        ):
            desc_f.write(description)
            desc_path = desc_f.name
            design_f.write(design)
            design_path = design_f.name

        try:
            cmd = [
                "bd", "create", title,
                "-t", bead_type,
                "-p", str(priority),
                "--body-file", desc_path,
                "--design-file", design_path,
                "--acceptance", acceptance,
                "--notes", notes,
                "--silent",
            ]
            stdout, _ = await self._run(*cmd)
            bead_id = stdout.strip()
            if not bead_id:
                raise BeadsError("bd create returned an empty bead ID")
        finally:
            os.unlink(desc_path)
            os.unlink(design_path)

        # Wire up dependencies: new bead is blocked-by each dep.
        for dep_id in deps:
            await self._run(
                "bd", "dep", "add", bead_id, "--blocked-by", dep_id
            )

        return bead_id

    async def close_bead(self, bead_id: str, reason: str) -> bool:
        """Close a bead via bd close.

        Args:
            bead_id: The bead ID to close.
            reason:  Human-readable reason for closing.

        Returns:
            True on success.  Raises BeadsError on failure.
        """
        await self._run("bd", "close", bead_id, reason)
        return True

    async def show_bead(self, bead_id: str) -> dict[str, Any]:
        """Get bead details via bd show --json.

        Args:
            bead_id: The bead ID to retrieve.

        Returns:
            Parsed JSON dict of the bead's details.
        """
        stdout, _ = await self._run("bd", "show", bead_id, "--json")
        data = json.loads(stdout)
        # bd show --json may return a list (when multiple IDs are passed) or a
        # single object.  Normalise to a dict.
        if isinstance(data, list):
            if not data:
                raise BeadsError(f"bd show returned empty list for bead {bead_id!r}")
            return data[0]
        return data

    async def list_open_beads(
        self, decomposition_id: str | None = None
    ) -> list[dict[str, Any]]:
        """List open beads, optionally filtered by decomposition_id in notes.

        Args:
            decomposition_id: If provided, only beads whose notes JSON contains
                              a ``decomposition_id`` field equal to this value
                              are returned.

        Returns:
            List of bead detail dicts.
        """
        stdout, _ = await self._run("bd", "list", "--status", "open", "--json")
        beads: list[dict[str, Any]] = json.loads(stdout) if stdout else []

        if decomposition_id is None:
            return beads

        # Filter by decomposition_id stored inside the notes JSON field.
        filtered: list[dict[str, Any]] = []
        for bead in beads:
            raw_notes = bead.get("notes", "") or ""
            if not raw_notes:
                continue
            try:
                notes_data = json.loads(raw_notes)
                if notes_data.get("decomposition_id") == decomposition_id:
                    filtered.append(bead)
            except (json.JSONDecodeError, AttributeError):
                # notes is not JSON or doesn't have the field — skip.
                pass
        return filtered

    async def create_beads_transactional(
        self, beads: list[dict[str, Any]]
    ) -> list[str]:
        """Create all beads in topological order with rollback on failure.

        Each entry in *beads* must be a dict with the keyword arguments for
        :meth:`create_bead`:
        ``title``, ``bead_type``, ``priority``, ``deps``, ``description``,
        ``design``, ``acceptance``, ``notes``.

        If any creation fails, all previously created beads are closed with
        reason ``"decomposition failed — partial cleanup"`` before the
        exception is re-raised.

        Args:
            beads: Ordered list of bead-creation parameter dicts.  The order
                   must already respect topological dependencies (dependencies
                   first).

        Returns:
            List of created bead IDs in the same order as *beads*.

        Raises:
            BeadsError: If any bead creation fails (after rolling back).
        """
        created_ids: list[str] = []

        for bead_kwargs in beads:
            try:
                bead_id = await self.create_bead(
                    title=bead_kwargs["title"],
                    bead_type=bead_kwargs["bead_type"],
                    priority=bead_kwargs["priority"],
                    deps=bead_kwargs.get("deps", []),
                    description=bead_kwargs.get("description", ""),
                    design=bead_kwargs.get("design", ""),
                    acceptance=bead_kwargs.get("acceptance", ""),
                    notes=bead_kwargs.get("notes", ""),
                )
                created_ids.append(bead_id)
            except Exception as exc:
                # Roll back: close everything we already created.
                rollback_errors: list[str] = []
                for rollback_id in created_ids:
                    try:
                        await self.close_bead(
                            rollback_id,
                            "decomposition failed \u2014 partial cleanup",
                        )
                    except Exception as rb_exc:  # noqa: BLE001
                        rollback_errors.append(f"{rollback_id}: {rb_exc}")

                msg = (
                    f"Bead creation failed for {bead_kwargs.get('title')!r}: {exc}"
                )
                if rollback_errors:
                    msg += f"\nRollback errors: {'; '.join(rollback_errors)}"
                raise BeadsError(msg) from exc

        return created_ids
