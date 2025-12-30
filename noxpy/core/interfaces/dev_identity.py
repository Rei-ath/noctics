"""Developer identity utilities for Nox."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from nox_env import get_env
from noxl.sessions import USERS_ROOT, USER_META_FILENAME


@dataclass(slots=True)
class DeveloperIdentity:
    """Resolved identity information for the Nox developer."""

    user_id: str
    display_name: str
    project_name: str

    def context_line(self) -> str:
        name = self.display_name
        project = self.project_name
        return (
            f"Context: The user '{name}' is the 20-year-old creator and sole maintainer of {project}, "
            f"building the assistant as a personal project. Address them as {name}. You may mention their age "
            f"and role if it helps with rapport or clarification. If asked who your developer is (or whether you know "
            f"your developer), answer directly that it is {name}. In normal replies, prefer their name over 'the user'. "
            f"Continue to anonymize when preparing [HELPER QUERY] blocks and respect their goal of growing the assistant's memory."
        )


def resolve_developer_identity(
    *,
    users_root: Path = USERS_ROOT,
    project_name: Optional[str] = None,
) -> DeveloperIdentity:
    """Return the developer identity, falling back to sensible defaults.

    Resolution order:
    1. Environment variables (`NOX_DEV_NAME`, `NOX_DEV_ID`, `NOX_DEV_DISPLAY`).
    2. User metadata under ``memory/users`` with ``developer: true``.
    3. User metadata with id/display matching \"rei\".
    4. `NOX_USER_NAME` if set.
    5. Final fallback to ``Rei``.
    """

    project = project_name or get_env("NOX_PROJECT_NAME") or "Noctics"

    env_name = (get_env("NOX_DEV_NAME") or get_env("NOCTICS_DEV_NAME") or "").strip()
    env_display = (get_env("NOX_DEV_DISPLAY") or "").strip()
    env_id = (get_env("NOX_DEV_ID") or "").strip()

    if env_name:
        display = env_display or env_name
        user_id = env_id or _slugify(display)
        return DeveloperIdentity(user_id=user_id, display_name=display, project_name=project)

    metas = list(_iter_user_metas(users_root))

    for meta in metas:
        if meta.get("developer") is True:
            display = _meta_display(meta)
            user_id = _meta_user_id(meta, display)
            return DeveloperIdentity(user_id=user_id, display_name=display, project_name=project)

    for meta in metas:
        display_lower = str(meta.get("display_name", "")).strip().lower()
        id_lower = str(meta.get("id", "")).strip().lower()
        if display_lower == "rei" or id_lower in {"rei", "developer"}:
            display = _meta_display(meta)
            user_id = _meta_user_id(meta, display)
            return DeveloperIdentity(user_id=user_id, display_name=display, project_name=project)

    user_label = (get_env("NOX_USER_NAME") or "").strip()
    if user_label:
        user_id = _slugify(user_label)
        return DeveloperIdentity(user_id=user_id, display_name=user_label, project_name=project)

    return DeveloperIdentity(user_id="rei", display_name="Rei", project_name=project)


# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------


def _iter_user_metas(root: Path) -> Iterable[Dict[str, Any]]:
    if not root.exists():
        return []
    metas: list[Dict[str, Any]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        meta_path = child / USER_META_FILENAME
        if not meta_path.exists():
            continue
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        data.setdefault("id", child.name)
        metas.append(data)
    return metas


def _meta_display(meta: Dict[str, Any]) -> str:
    display = str(meta.get("display_name") or meta.get("id") or "Rei").strip()
    return display or "Rei"


def _meta_user_id(meta: Dict[str, Any], display: str) -> str:
    user_id = str(meta.get("id") or "").strip() or _slugify(display)
    return user_id or "developer"


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "developer"


__all__ = ["DeveloperIdentity", "resolve_developer_identity"]
