"""CLI runtime identity utilities."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from central.colors import color
from interfaces.dev_identity import resolve_developer_identity
from interfaces.session_logger import USER_META_FILENAME
from nox_env import get_env
from noxl import USERS_ROOT

__all__ = ["RuntimeIdentity", "resolve_runtime_identity"]


@dataclass(slots=True)
class RuntimeIdentity:
    """Runtime identity information for CLI sessions."""

    user_id: str
    display_name: str
    _context_line: str = ""
    created_user: bool = False

    def context_line(self) -> str:
        return self._context_line


def _slugify_name(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "user"


def _list_user_profiles(users_root: Path) -> List[Dict[str, str]]:
    profiles: List[Dict[str, str]] = []
    if not users_root.exists():
        return profiles
    for child in sorted(users_root.iterdir()):
        if not child.is_dir():
            continue
        meta_path = child / USER_META_FILENAME
        display = child.name.replace("_", " ")
        user_id = child.name
        if meta_path.exists():
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            display = str(data.get("display_name") or display).strip() or display
            user_id = str(data.get("id") or user_id).strip() or user_id
        profiles.append({"user_id": user_id, "display_name": display})
    return profiles


def _ensure_user_profile(
    user_id: str,
    display_name: str,
    *,
    users_root: Path,
) -> bool:
    users_root.mkdir(parents=True, exist_ok=True)
    user_dir = users_root / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    meta_path = user_dir / USER_META_FILENAME
    data: Dict[str, Any]
    updated = False
    if meta_path.exists():
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    else:
        data = {}

    if data.get("id") != user_id:
        data["id"] = user_id
        updated = True
    if display_name and data.get("display_name") != display_name:
        data["display_name"] = display_name
        updated = True

    if updated or not meta_path.exists():
        meta_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    return False


def _prompt_for_user_selection(
    *,
    existing: List[Dict[str, str]],
    users_root: Path,
) -> RuntimeIdentity:
    while True:
        if existing:
            print(color("Available users:", fg="yellow", bold=True))
            for idx, profile in enumerate(existing, 1):
                print(
                    color(
                        f"  {idx}. {profile['display_name']} (id: {profile['user_id']})",
                        fg="yellow",
                    )
                )
        prompt = color("Enter a username (new or existing): ", fg="yellow")
        try:
            entered = input(prompt).strip()
        except EOFError:
            entered = ""
        if not entered:
            print(color("Please provide a username.", fg="red"))
            continue

        selection: Optional[Dict[str, str]] = None
        if existing:
            if entered.isdigit():
                index = int(entered)
                if 1 <= index <= len(existing):
                    selection = existing[index - 1]
            if selection is None:
                lookup = entered.lower()
                selection = next(
                    (
                        profile
                        for profile in existing
                        if profile["display_name"].lower() == lookup
                        or profile["user_id"].lower() == lookup
                    ),
                    None,
                )

        if selection is not None:
            user_id = selection["user_id"]
            display = selection["display_name"]
            _ensure_user_profile(user_id, display, users_root=users_root)
            return RuntimeIdentity(user_id=user_id, display_name=display, created_user=False)

        display_name = entered
        user_id = _slugify_name(display_name)
        matching = next(
            (
                profile
                for profile in existing
                if profile["user_id"].lower() == user_id.lower()
            ),
            None,
        )
        if matching is not None:
            _ensure_user_profile(matching["user_id"], matching["display_name"], users_root=users_root)
            return RuntimeIdentity(
                user_id=matching["user_id"],
                display_name=matching["display_name"],
                created_user=False,
            )

        _ensure_user_profile(user_id, display_name, users_root=users_root)
        return RuntimeIdentity(user_id=user_id, display_name=display_name, created_user=True)


def resolve_runtime_identity(
    *,
    dev_mode: bool,
    initial_label: str,
    interactive: bool,
    users_root: Path = USERS_ROOT,
) -> RuntimeIdentity:
    if dev_mode:
        developer = resolve_developer_identity(users_root=users_root)
        return RuntimeIdentity(
            user_id=developer.user_id,
            display_name=developer.display_name,
            _context_line=developer.context_line(),
            created_user=False,
        )

    existing = _list_user_profiles(users_root)
    normalized = (initial_label or "").strip()

    if interactive:
        return _prompt_for_user_selection(existing=existing, users_root=users_root)

    if normalized:
        display_name = normalized
    elif existing:
        display_name = existing[0]["display_name"]
    else:
        display_name = (get_env("NOX_USER_NAME") or "Guest").strip() or "Guest"

    user_id = _slugify_name(display_name)
    created = _ensure_user_profile(user_id, display_name, users_root=users_root)
    return RuntimeIdentity(user_id=user_id, display_name=display_name, created_user=created)
