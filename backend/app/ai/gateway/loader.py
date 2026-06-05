"""Versioned prompt-template loader.

Templates live as files under ``settings.ai.prompt_template_dir``, organised by
name and version::

    <prompt_template_dir>/
        nl_to_sql/
            v1/
                system.txt      ← system-role prompt for NL→SQL
                user.txt        ← user-turn template for NL→SQL
        insights/
            v1/
                system.txt
        …

A "template" in this context is a plain-text file that may contain
``{variable}`` placeholders rendered via Python's ``str.format_map()``.

The directory root is always taken from ``settings.ai.prompt_template_dir``
(env var ``AI__PROMPT_TEMPLATE_DIR``) — it is never hardcoded.

Usage::

    loader = PromptLoader(prompt_template_dir="/path/to/your/prompts")  # from settings
    text = loader.load("nl_to_sql", "v1", "system")
    rendered = loader.render("nl_to_sql", "v1", "user", metrics="revenue, churn")

Errors
------
- ``TemplateNotFoundError`` if the file does not exist.  The message includes the
  full resolved path so operators can diagnose quickly.
- ``TemplateRenderError`` if a required ``{variable}`` placeholder is missing from
  the keyword arguments passed to ``render()``.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class TemplateNotFoundError(Exception):
    """Raised when the requested template file does not exist.

    Args:
        name: Template name (directory under ``prompt_template_dir``).
        version: Template version string (e.g. ``"v1"``).
        filename: The filename within the versioned directory.
        path: The fully resolved path that was not found.
    """

    def __init__(self, name: str, version: str, filename: str, path: Path) -> None:
        super().__init__(
            f"Prompt template not found: name={name!r} version={version!r} "
            f"file={filename!r} — looked at {path}"
        )
        self.name = name
        self.version = version
        self.filename = filename
        self.path = path


class TemplateRenderError(Exception):
    """Raised when ``str.format_map()`` fails due to a missing placeholder key.

    Args:
        name: Template name.
        version: Template version string.
        filename: The filename within the versioned directory.
        missing_key: The placeholder key that was not supplied.
    """

    def __init__(self, name: str, version: str, filename: str, missing_key: str) -> None:
        super().__init__(
            f"Prompt template render error: name={name!r} version={version!r} "
            f"file={filename!r} — missing key {missing_key!r}"
        )
        self.name = name
        self.version = version
        self.filename = filename
        self.missing_key = missing_key


class PromptLoader:
    """Load and render versioned prompt templates from the configured directory.

    Args:
        prompt_template_dir: Absolute or relative path to the directory that
            contains versioned template sub-directories.  Comes from
            ``settings.ai.prompt_template_dir`` — never hardcoded.
    """

    def __init__(self, prompt_template_dir: str) -> None:
        self._root = Path(prompt_template_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, name: str, version: str, filename: str = "system") -> str:
        """Load the raw (unrendered) text of a versioned template.

        File path resolved as::

            <prompt_template_dir>/<name>/<version>/<filename>.txt

        Args:
            name: Template name (e.g. ``"nl_to_sql"``).
            version: Version string (e.g. ``"v1"``).
            filename: Filename without extension (e.g. ``"system"`` or ``"user"``).
                Defaults to ``"system"``.

        Returns:
            The raw template text.

        Raises:
            TemplateNotFoundError: If the file does not exist.
        """
        path = self._resolve(name, version, filename)
        if not path.exists():
            raise TemplateNotFoundError(name, version, filename, path)
        text = path.read_text(encoding="utf-8")
        logger.debug(
            "PromptLoader.load name=%r version=%r file=%r chars=%d",
            name,
            version,
            filename,
            len(text),
        )
        return text

    def render(
        self,
        name: str,
        version: str,
        filename: str = "system",
        **variables: str,
    ) -> str:
        """Load and render a versioned template with ``{variable}`` substitution.

        Uses ``str.format_map()`` so only named placeholders are substituted;
        literal braces must be escaped as ``{{`` and ``}}``.

        Args:
            name: Template name (e.g. ``"nl_to_sql"``).
            version: Version string (e.g. ``"v1"``).
            filename: Filename without extension.  Defaults to ``"system"``.
            **variables: Keyword arguments substituted for ``{key}`` placeholders.

        Returns:
            The rendered template string.

        Raises:
            TemplateNotFoundError: If the file does not exist.
            TemplateRenderError: If a required placeholder is missing.
        """
        raw = self.load(name, version, filename)
        try:
            return raw.format_map(variables)
        except KeyError as exc:
            missing_key = exc.args[0]
            raise TemplateRenderError(name, version, filename, missing_key) from exc

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _resolve(self, name: str, version: str, filename: str) -> Path:
        """Return the resolved ``Path`` for a template file (may not exist).

        Fails closed on path traversal: ``name``/``version``/``filename`` may one
        day arrive from an API parameter, so a ``..`` segment (or absolute path)
        that escapes the template root is rejected rather than allowed to read an
        arbitrary file. ``pathlib`` does NOT sanitise ``..`` on its own.
        """
        resolved = (self._root / name / version / f"{filename}.txt").resolve()
        root = self._root.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError(
                f"Prompt template path escapes the template root: "
                f"name={name!r} version={version!r} file={filename!r}"
            )
        return resolved


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


def get_prompt_loader(
    settings: Settings = Depends(get_settings),  # noqa: B008
) -> PromptLoader:
    """FastAPI dependency: return a ``PromptLoader`` wired from settings.

    The directory is taken from ``settings.ai.prompt_template_dir`` — the env var
    ``AI__PROMPT_TEMPLATE_DIR`` controls which directory is used in each deployment.
    Override in tests via ``app.dependency_overrides`` or construct directly.

    Example::

        @router.post("/nl-to-sql")
        async def nl_to_sql(
            loader: PromptLoader = Depends(get_prompt_loader),
        ) -> str:
            system = loader.render("nl_to_sql", "v1", "system", tenant_db="acme_db")
            …
    """
    return PromptLoader(prompt_template_dir=settings.ai.prompt_template_dir)
