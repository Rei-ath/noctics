"""
Minimal session logger for fine-tuning data capture.

Writes one JSONL file per session under memory/sessions/ with
each turn captured as an example in the shape:

  {"messages": [{"role": "system"|"user"|"assistant", "content": "..."}, ...],
   "meta": {"model": "...", "sanitized": true/false, "turn": N, "ts": "ISO"}}

No external dependencies, append-only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .paths import resolve_sessions_root, resolve_users_root

USER_SESSIONS_DIR = "sessions"
USER_META_FILENAME = "user.json"


def format_session_display_name(session_id: str) -> str:
    """Return a human-friendly label for a session file stem.

    Examples:
        session-20250913-123456 -> "Session 2025-09-13 12:34:56 UTC"
        session-merged-20250913-123456 -> "Merged session 2025-09-13 12:34:56 UTC"
    Fallback: replace dashes with spaces and title-case the id.
    """
    base = session_id or ""
    prefixes = [
        ("session-merged-", "Merged session"),
        ("session-", "Session"),
    ]
    for prefix, label in prefixes:
        if base.startswith(prefix):
            suffix = base[len(prefix):]
            try:
                dt = datetime.strptime(suffix, "%Y%m%d-%H%M%S")
            except ValueError:
                break
            return f"{label} {dt.strftime('%Y-%m-%d %H:%M:%S')} UTC"
    # Fallback formatting
    pretty = base.replace("-", " ").strip()
    return pretty.title() if pretty else "Session"


@dataclass
class SessionLogger:
    model: str
    sanitized: bool
    dirpath: Optional[Path] = None
    users_root: Optional[Path] = None
    user_id: Optional[str] = None
    user_display: Optional[str] = None
    _file: Optional[Path] = None
    _meta_file: Optional[Path] = None
    _turn: int = 0
    _title: Optional[str] = None
    _title_custom: bool = False
    _display_name: Optional[str] = None
    _records: List[Dict[str, Any]] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.dirpath = Path(self.dirpath) if self.dirpath is not None else resolve_sessions_root()
        self.users_root = Path(self.users_root) if self.users_root is not None else resolve_users_root()

    def start(self) -> None:
        # Create a date-based subfolder (UTC) for sessions, e.g.,
        # memory/sessions/2025-09-13/session-20250913-123456.jsonl
        base = self._resolve_session_root()
        now_utc = datetime.now(timezone.utc)
        date_folder = now_utc.date().isoformat()  # YYYY-MM-DD
        dated_dir = base / date_folder
        dated_dir.mkdir(parents=True, exist_ok=True)

        ts = now_utc.strftime("%Y%m%d-%H%M%S")
        self._file = dated_dir / f"session-{ts}.jsonl"
        self._display_name = format_session_display_name(self._file.stem)
        self._records = []
        self._turn = 0
        if not self._file.exists():
            self._file.touch()
        else:
            self._turn = sum(1 for _ in self._iter_jsonl(self._file))

        # Create/initialize sidecar meta file
        self._meta_file = self._file.with_name(self._file.stem + ".meta.json")
        self._write_meta(initial=True)

    def log_turn(self, messages: List[Dict[str, Any]]) -> None:
        if self._file is None:
            self.start()
        self._turn += 1
        rec = {
            "messages": messages,
            "meta": {
                "model": self.model,
                "sanitized": bool(self.sanitized),
                "turn": self._turn,
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "file_name": self._file.name if self._file else None,
                "display_name": self._display_name,
            },
        }
        if self._file is not None:
            if self._file.suffix == ".jsonl":
                line = json.dumps(rec, ensure_ascii=False)
                with self._file.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            else:
                self._records.append(rec)
                self._file.write_text(
                    json.dumps(self._records, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
        self._write_meta()

    def load_existing(self, log_path: Path) -> None:
        self._file = log_path
        self._meta_file = log_path.with_name(log_path.stem + ".meta.json")
        self._infer_user_from_path(log_path)
        if log_path.suffix == ".jsonl":
            self._records = []
            self._turn = sum(1 for _ in self._iter_jsonl(log_path))
        else:
            try:
                data = json.loads(log_path.read_text(encoding="utf-8"))
            except Exception:
                data = []
            self._records = data if isinstance(data, list) else []
            self._turn = len(self._records)
        if self._meta_file.exists():
            try:
                meta = json.loads(self._meta_file.read_text(encoding="utf-8"))
            except Exception:
                meta = {}
            self._title = meta.get("title")
            self._title_custom = bool(meta.get("custom", False))
            if not self._display_name:
                self._display_name = meta.get("display_name")
        if not self._display_name:
            self._display_name = format_session_display_name(log_path.stem)

    # -----------------
    # Meta sidecar utils
    # -----------------
    def _write_meta(self, initial: bool = False) -> None:
        if self._file is None:
            return
        if self._meta_file is None:
            self._meta_file = self._file.with_name(self._file.stem + ".meta.json")
        created_iso: Optional[str] = None
        if self._meta_file.exists() and not initial:
            try:
                data = json.loads(self._meta_file.read_text(encoding="utf-8"))
                created_iso = data.get("created")
                existing_title = data.get("title")
                existing_custom = bool(data.get("custom", False))
                if self._title is None:
                    self._title = existing_title
                    self._title_custom = existing_custom
                elif not self._title_custom and self._title == existing_title:
                    self._title_custom = existing_custom
                if self._display_name is None:
                    self._display_name = data.get("display_name")
            except Exception:
                created_iso = None
        now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        meta = {
            "id": self._file.stem,
            "path": str(self._file),
            "model": self.model,
            "sanitized": bool(self.sanitized),
            "turns": self._turn,
            "created": created_iso or now,
            "updated": now,
            "title": self._title,
            "custom": bool(self._title_custom),
            "file_name": self._file.name if self._file else None,
            "display_name": self._display_name or format_session_display_name(self._file.stem),
        }
        if self.user_id:
            meta["user_id"] = self.user_id
            meta["user_display"] = self.user_display or self.user_id
        self._meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def set_title(self, title: str, *, custom: bool = True) -> None:
        self._title = title.strip() if title else None
        self._title_custom = bool(custom)
        self._write_meta()

    def get_title(self) -> Optional[str]:
        return self._title

    def get_meta(self) -> Dict[str, Any]:
        if self._meta_file and self._meta_file.exists():
            try:
                return json.loads(self._meta_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        # Fallback
        return {
            "id": self._file.stem if self._file else None,
            "path": str(self._file) if self._file else None,
            "model": self.model,
            "sanitized": bool(self.sanitized),
            "turns": self._turn,
            "title": self._title,
            "custom": bool(self._title_custom),
            "file_name": self._file.name if self._file else None,
            "display_name": self._display_name if self._display_name else (format_session_display_name(self._file.stem) if self._file else None),
            "user_id": self.user_id,
            "user_display": self.user_display,
        }

    def meta_path(self) -> Optional[Path]:
        return self._meta_file

    def log_path(self) -> Optional[Path]:
        return self._file

    # -----------------
    # User-aware utilities
    # -----------------

    def _resolve_session_root(self) -> Path:
        if self.user_id:
            user_root = self.users_root / self.user_id
            sessions_dir = user_root / USER_SESSIONS_DIR
            sessions_dir.mkdir(parents=True, exist_ok=True)
            if not self.user_display and self.user_id:
                self.user_display = self.user_id.replace("_", " ")
            self._ensure_user_meta(user_root)
            self.dirpath = sessions_dir
            return sessions_dir

        self.dirpath.mkdir(parents=True, exist_ok=True)
        return self.dirpath

    def _ensure_user_meta(self, user_root: Path) -> None:
        meta_path = user_root / USER_META_FILENAME
        data: Dict[str, Any]
        if meta_path.exists():
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        else:
            data = {}

        updated = False
        if data.get("id") != self.user_id:
            data["id"] = self.user_id
            updated = True
        display = self.user_display or data.get("display_name") or (self.user_id.replace("_", " ") if self.user_id else None)
        if display and data.get("display_name") != display:
            data["display_name"] = display
            updated = True

        if updated or not meta_path.exists():
            meta_path.parent.mkdir(parents=True, exist_ok=True)
            meta_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        self.user_display = data.get("display_name") or self.user_display or (self.user_id.replace("_", " ") if self.user_id else None)

    def _iter_jsonl(self, path: Path):
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except Exception:
                        continue
        except FileNotFoundError:
            return

    def _infer_user_from_path(self, log_path: Path) -> None:
        resolved = log_path.resolve()
        # sessions/<day>/file.json -> sessions root is parent of day directory
        sessions_root = resolved.parent.parent
        user_root = sessions_root.parent

        if user_root.name != "" and user_root.parent and user_root.parent.name == "users":
            self.users_root = user_root.parent
            self.user_id = user_root.name
            self.dirpath = sessions_root
            meta_path = user_root / USER_META_FILENAME
            if meta_path.exists():
                try:
                    data = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
                self.user_display = data.get("display_name") or data.get("id")
            else:
                self.user_display = self.user_id.replace("_", " ")
            return

        # Legacy structure
        self.dirpath = sessions_root
