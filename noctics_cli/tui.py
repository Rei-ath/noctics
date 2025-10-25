"""Curses-powered session browser for Noctics."""

from __future__ import annotations

import curses
import textwrap
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from noxl import list_sessions as noxl_list_sessions
from noxl import load_session_messages


@dataclass(slots=True)
class SessionSummary:
    ident: str
    title: str
    updated: str
    path: str
    user: Optional[str]


def _normalise_content(content: object) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_normalise_content(item) for item in content)
    if isinstance(content, dict):
        if "text" in content:
            return _normalise_content(content["text"])
        return "\n".join(
            f"{key}: {_normalise_content(value)}" for key, value in content.items()
        )
    return str(content)


def format_messages(
    messages: Sequence[dict],
    *,
    width: int,
    max_lines: int,
) -> List[str]:
    """Return a wrapped preview of messages for display."""

    lines: List[str] = []
    wrapper = textwrap.TextWrapper(width=width, subsequent_indent="  ")

    for message in messages:
        role = str(message.get("role") or "").strip().upper() or "ANON"
        content = _normalise_content(message.get("content"))
        if not content:
            continue
        for paragraph in content.splitlines():
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            wrapped = wrapper.wrap(paragraph) or [""]
            wrapped[0] = f"{role}: {wrapped[0]}"
            lines.extend(wrapped)
        lines.append("")
        if len(lines) >= max_lines:
            break

    return lines[:max_lines] if lines else ["<no content>"]


def _load_sessions(limit: int = 200) -> List[SessionSummary]:
    items = noxl_list_sessions()
    summaries: List[SessionSummary] = []
    for item in items[:limit]:
        ident = str(item.get("id") or item.get("path") or "")
        title = str(item.get("title") or "Untitled Session")
        updated = str(item.get("updated") or item.get("created") or "")
        path = str(item.get("path") or ident)
        user = item.get("user_display")
        summaries.append(SessionSummary(ident=ident, title=title, updated=updated, path=path, user=user))
    return summaries


class SessionTui:
    def __init__(self, screen: "curses.window") -> None:
        self.screen = screen
        self.sessions: List[SessionSummary] = []
        self.selected_index = 0
        self.current_messages: List[str] = []
        self.status: str = "q: quit • r: refresh • enter: view"

    # -----------------------------
    # Lifecycle
    # -----------------------------
    def run(self) -> None:
        curses.curs_set(0)
        curses.use_default_colors()
        self.screen.nodelay(False)
        self.screen.keypad(True)
        self.load_sessions()
        self.draw()

        while True:
            key = self.screen.getch()
            if key in (ord("q"), ord("Q")):
                break
            if key in (ord("r"), ord("R")):
                self.load_sessions()
            elif key in (curses.KEY_UP, ord("k"), ord("K")):
                self.move_selection(-1)
            elif key in (curses.KEY_DOWN, ord("j"), ord("J")):
                self.move_selection(1)
            elif key in (curses.KEY_NPAGE,):
                self.move_selection(10)
            elif key in (curses.KEY_PPAGE,):
                self.move_selection(-10)
            elif key in (curses.KEY_ENTER, 10, 13, ord("o"), ord("O")):
                self.load_selected_messages()
            elif key == curses.KEY_RESIZE:
                pass  # handled by draw
            self.draw()

    def load_sessions(self) -> None:
        try:
            self.sessions = _load_sessions()
            if self.selected_index >= len(self.sessions):
                self.selected_index = max(0, len(self.sessions) - 1)
            self.status = f"Loaded {len(self.sessions)} sessions."
        except Exception as exc:
            self.sessions = []
            self.selected_index = 0
            self.status = f"Failed to load sessions: {exc}"
            self.current_messages = []

    def load_selected_messages(self) -> None:
        if not self.sessions:
            self.current_messages = ["<no sessions>"]
            return
        session = self.sessions[self.selected_index]
        try:
            messages = load_session_messages(session.ident) or []
            height, width = self._detail_dimensions()
            detail_lines = format_messages(messages, width=max(width - 2, 20), max_lines=max(height - 4, 10))
            self.current_messages = detail_lines
            self.status = f"Viewing {session.ident}"
        except Exception as exc:
            self.current_messages = [f"Error loading session: {exc}"]
            self.status = "Encountered an error while loading the selected session."

    def move_selection(self, delta: int) -> None:
        if not self.sessions:
            return
        self.selected_index = (self.selected_index + delta) % len(self.sessions)

    # -----------------------------
    # Rendering
    # -----------------------------
    def draw(self) -> None:
        self.screen.erase()
        height, width = self.screen.getmaxyx()

        if height < 10 or width < 40:
            self.screen.addstr(0, 0, "Terminal too small for the dashboard (min 40x10).")
            self.screen.refresh()
            return

        list_width = max(30, width // 3)
        detail_width = width - list_width - 1

        # Draw session list border
        self.screen.box()
        self.screen.vline(0, list_width, curses.ACS_VLINE, height)
        self.screen.addstr(0, 2, " Sessions ")

        # Draw sessions
        for idx, session in enumerate(self.sessions[: height - 4]):
            y = idx + 1
            label = f"{session.title}"
            if session.updated:
                label += f" [{session.updated}]"
            if len(label) > list_width - 2:
                label = label[: list_width - 5] + "..."
            if idx == self.selected_index:
                self.screen.attron(curses.A_REVERSE)
            self.screen.addstr(y, 1, label.ljust(list_width - 1))
            if idx == self.selected_index:
                self.screen.attroff(curses.A_REVERSE)

        if not self.sessions:
            self.screen.addstr(1, 1, "(no sessions found)")

        # Draw detail panel
        self.screen.addstr(0, list_width + 2, " Details ")
        detail_y = 1
        detail_x = list_width + 2
        detail_height = height - 4
        detail_width = width - detail_x - 1

        if self.sessions:
            session = self.sessions[self.selected_index]
            header = f"{session.title} ({session.ident})"
            self.screen.addstr(detail_y, detail_x, header[: detail_width])
            detail_y += 2
            if not self.current_messages:
                self.load_selected_messages()
            for line in self.current_messages[: detail_height]:
                self.screen.addstr(detail_y, detail_x, line[: detail_width])
                detail_y += 1
        else:
            self.screen.addstr(detail_y, detail_x, "Press r to reload sessions.")

        # Status bar
        status = self.status[: width - 1]
        self.screen.hline(height - 2, 1, curses.ACS_HLINE, width - 2)
        self.screen.addstr(height - 1, 2, status)
        self.screen.refresh()

    def _detail_dimensions(self) -> Tuple[int, int]:
        height, width = self.screen.getmaxyx()
        list_width = max(30, width // 3)
        detail_width = width - list_width - 4
        detail_height = height - 4
        return detail_height, detail_width


def main(argv: Optional[Iterable[str]] = None) -> int:
    """Entry point mirroring the CLI command signature."""

    def _wrapped(screen: "curses.window") -> None:
        app = SessionTui(screen)
        app.run()

    curses.wrapper(_wrapped)
    return 0


__all__ = ["main", "format_messages"]
