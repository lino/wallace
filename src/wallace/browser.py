"""Minimalistic single-viewport `curses` TUI browser state and terminal driver."""

from __future__ import annotations

import contextlib
import curses
import os
import sys
from datetime import datetime
from typing import Protocol

from wallace.aggregator import slice_record_by_bounds
from wallace.browser_view import SOURCE_TABS, StyledLine, render_browser_lines
from wallace.config import AppConfig
from wallace.message_loader import load_conversation_messages, resolve_conversation_record
from wallace.metrics import record_browser_view
from wallace.models import ConversationMessage, ConversationRecord, sortable_cost
from wallace.timeframes import current_reference_time, resolve_timeframe_spec

__all__ = [
    "BROWSER_TIMEFRAMES",
    "BrowserState",
    "CursesWindowLike",
    "StyledLine",
    "launch_browser",
    "render_browser_lines",
    "run_curses_browser",
]

SORT_MODES: tuple[str, ...] = ("recent", "tokens", "cost")
BROWSER_TIMEFRAMES: tuple[str, ...] = (
    "all",
    "today",
    "yesterday",
    "7d",
    "30d",
    "this-month",
    "last-month",
)


class CursesWindowLike(Protocol):
    """Minimal structural protocol satisfied by `curses.window` and test doubles."""

    def keypad(self, flag: bool) -> None:
        """Enable or disable keypad translation."""

    def erase(self) -> None:
        """Clear window buffer."""

    def refresh(self) -> None:
        """Flush buffered updates to terminal."""

    def getmaxyx(self) -> tuple[int, int]:
        """Return `(height, width)` of the terminal window."""

    def addnstr(self, y: int, x: int, text: str, n: int, attr: int = 0) -> None:
        """Write at most `n` characters at `(y, x)`."""

    def getch(self) -> int:
        """Read next keycode."""


class BrowserState:
    """Deterministic state machine driving the single-viewport conversation browser."""

    def __init__(
        self,
        records: list[ConversationRecord],
        config: AppConfig,
        *,
        initial_source: str = "all",
        initial_query: str = "",
        initial_timeframe: str = "all",
        initial_conversation_id: str = "",
        now: datetime | None = None,
    ) -> None:
        """Initialize browser state with scanned `records` and optional initial filters."""
        self.records = list(records)
        self.config = config
        self._now = now
        self.source_tab = initial_source if initial_source in SOURCE_TABS else "all"
        self.sort_mode = "recent"
        self.filter_query = initial_query
        tf_bounds = resolve_timeframe_spec(initial_timeframe, now=self._now)
        self.timeframe = tf_bounds.label
        self._timeframe_cycle = (
            BROWSER_TIMEFRAMES
            if self.timeframe in BROWSER_TIMEFRAMES
            else ("all", self.timeframe, *BROWSER_TIMEFRAMES[1:])
        )
        self.input_mode = False
        self.mode = "list"
        self.detail_subview = "messages"
        self.show_details = False
        self.show_help = False
        self.selected_index = 0
        self.list_scroll = 0
        self.detail_scroll = 0
        self._msg_cache: dict[str, list[ConversationMessage]] = {}
        self._detail_record: ConversationRecord | None = None
        if initial_conversation_id:
            with contextlib.suppress(LookupError):
                self._enter_detail(
                    resolve_conversation_record(self.records, initial_conversation_id)
                )

    @property
    def visible_records(self) -> list[ConversationRecord]:
        """Return conversations matching `source_tab`, `timeframe`, and `filter_query`."""
        needle = self.filter_query.strip().lower()
        ref_now = current_reference_time(self._now)
        bounds = resolve_timeframe_spec(self.timeframe, now=ref_now)
        filtered: list[ConversationRecord] = []
        for rec in self.records:
            if not (_matches_tab(rec.source, self.source_tab) and _matches_search(rec, needle)):
                continue
            sliced = slice_record_by_bounds(rec, bounds)
            if sliced is not None:
                filtered.append(sliced)
        if self.sort_mode == "tokens":
            filtered.sort(
                key=lambda r: (-r.total_tokens, -sortable_cost(r.cost_usd), r.conversation_id)
            )
        elif self.sort_mode == "cost":
            filtered.sort(
                key=lambda r: (-sortable_cost(r.cost_usd), -r.total_tokens, r.conversation_id)
            )
        else:
            filtered.sort(
                key=lambda r: (r.last_timestamp or r.started_at, r.total_tokens),
                reverse=True,
            )
        return filtered

    def active_record(self) -> ConversationRecord | None:
        """Return currently opened detail record or highlighted list record."""
        if self.mode == "detail" and self._detail_record is not None:
            return self._detail_record
        vis = self.visible_records
        if not vis:
            return None
        return vis[min(max(self.selected_index, 0), len(vis) - 1)]

    def active_messages(self) -> list[ConversationMessage]:
        """Lazily load and cache chronological messages for `active_record()`."""
        rec = self.active_record()
        if rec is None:
            return []
        cached = self._msg_cache.get(rec.conversation_id)
        if cached is None:
            cached = load_conversation_messages(rec, self.config)
            self._msg_cache[rec.conversation_id] = cached
        return cached

    def _enter_detail(self, record: ConversationRecord) -> None:
        """Transition into detail view for `record` and record bounded telemetry."""
        self._detail_record = record
        self.mode = "detail"
        self.detail_subview = "messages"
        self.detail_scroll = 0
        self.active_messages()
        record_browser_view(source=record.source, view="detail")

    def handle_key(self, key: str, page_size: int = 18) -> bool:
        """Process a normalized key token; return `True` when the user exits."""
        if self.show_help:
            if key in ("?", "ESC", "q", "ENTER"):
                self.show_help = False
            return False
        if self.input_mode:
            self._handle_filter_input(key)
            return False
        if key == "?":
            self.show_help = True
            return False
        if self.mode == "detail":
            return self._handle_detail_key(key, page_size)
        return self._handle_list_key(key, page_size)

    def _handle_filter_input(self, key: str) -> None:
        """Update `filter_query` while `/` search prompt is active."""
        if key == "ENTER":
            self.input_mode = False
        elif key == "ESC":
            self.filter_query, self.input_mode = "", False
        elif key == "BACKSPACE":
            self.filter_query = self.filter_query[:-1]
        elif len(key) == 1 and key.isprintable():
            self.filter_query += key
        self.selected_index, self.list_scroll = 0, 0

    def _cycle_source_tab(self, step: int) -> None:
        """Advance `source_tab` by `step` (`1` or `-1`) and reset list cursor."""
        idx = (SOURCE_TABS.index(self.source_tab) + step) % len(SOURCE_TABS)
        self.source_tab = SOURCE_TABS[idx]
        self.selected_index, self.list_scroll = 0, 0

    def _handle_list_key(self, key: str, page_size: int) -> bool:
        """Handle navigation, tab switching, sorting, and opening in list mode."""
        if key == "q":
            return True
        tab_steps = {"TAB": 1, "SHIFT_TAB": -1}
        if key in tab_steps:
            self._cycle_source_tab(tab_steps[key])
            return False
        if key in ("1", "2", "3", "4", "5"):
            self.source_tab = SOURCE_TABS[int(key) - 1]
            self.selected_index, self.list_scroll = 0, 0
            return False
        if key == "/":
            self.input_mode = True
            return False
        if key == "ESC":
            self.filter_query, self.selected_index, self.list_scroll = "", 0, 0
            return False
        if key == "s":
            self.sort_mode = SORT_MODES[(SORT_MODES.index(self.sort_mode) + 1) % len(SORT_MODES)]
            self.selected_index, self.list_scroll = 0, 0
            return False
        if key == "t":
            cycle = self._timeframe_cycle
            self.timeframe = cycle[(cycle.index(self.timeframe) + 1) % len(cycle)]
            self.selected_index, self.list_scroll = 0, 0
            return False
        if key in ("ENTER", "l", "RIGHT"):
            rec = self.active_record()
            if rec is not None:
                self._enter_detail(rec)
            return False
        self._move_list_cursor(key, max(page_size, 1))
        return False

    def _move_list_cursor(self, key: str, page_size: int) -> None:
        """Move `selected_index` and keep it visible inside `list_scroll`."""
        total = len(self.visible_records)
        if total == 0:
            self.selected_index, self.list_scroll = 0, 0
            return
        deltas = {
            "j": 1,
            "DOWN": 1,
            "k": -1,
            "UP": -1,
            "PGDN": page_size,
            " ": page_size,
            "PGUP": -page_size,
            "b": -page_size,
        }
        if key in deltas:
            self.selected_index = min(max(self.selected_index + deltas[key], 0), total - 1)
        elif key in ("g", "HOME"):
            self.selected_index = 0
        elif key in ("G", "END"):
            self.selected_index = total - 1
        if self.selected_index < self.list_scroll:
            self.list_scroll = self.selected_index
        elif self.selected_index >= self.list_scroll + page_size:
            self.list_scroll = self.selected_index - page_size + 1

    def _handle_detail_key(self, key: str, page_size: int) -> bool:
        """Handle scrolling, thinking/tool expansion, turns toggle, and back in detail mode."""
        if key == "q":
            return True
        if key in ("ESC", "h", "LEFT", "BACKSPACE"):
            self.mode = "list"
            return False
        if key == "t":
            self.show_details = not self.show_details
            return False
        if key == "v":
            self.detail_subview = "turns" if self.detail_subview == "messages" else "messages"
            self.detail_scroll = 0
            return False
        deltas = {
            "j": 1,
            "DOWN": 1,
            "k": -1,
            "UP": -1,
            "d": page_size,
            "PGDN": page_size,
            " ": page_size,
            "u": -page_size,
            "PGUP": -page_size,
            "b": -page_size,
        }
        if key in deltas:
            self.detail_scroll = max(self.detail_scroll + deltas[key], 0)
        elif key in ("g", "HOME"):
            self.detail_scroll = 0
        elif key in ("G", "END"):
            self.detail_scroll = 100_000
        return False


def _matches_tab(source: str, tab: str) -> bool:
    """Return `True` if `source` belongs to provider tab `tab`."""
    if tab == "all":
        return True
    return source in ("ide", "cli", "standalone") if tab == "agy" else source == tab


def _matches_search(rec: ConversationRecord, needle: str) -> bool:
    """Return `True` if `needle` matches project, feature, title, model, source, or ID."""
    if not needle:
        return True
    haystack = (
        f"{rec.source} {rec.project} {rec.feature} {rec.title} "
        f"{rec.primary_model} {rec.conversation_id}"
    ).lower()
    return needle in haystack


def _translate_curses_key(code: int) -> str:
    """Map an integer `curses.getch()` code to a normalized `BrowserState` key string."""
    special = {
        9: "TAB",
        curses.KEY_BTAB: "SHIFT_TAB",
        10: "ENTER",
        13: "ENTER",
        curses.KEY_ENTER: "ENTER",
        27: "ESC",
        curses.KEY_UP: "UP",
        curses.KEY_DOWN: "DOWN",
        curses.KEY_LEFT: "LEFT",
        curses.KEY_RIGHT: "RIGHT",
        curses.KEY_NPAGE: "PGDN",
        curses.KEY_PPAGE: "PGUP",
        curses.KEY_HOME: "HOME",
        curses.KEY_END: "END",
        curses.KEY_BACKSPACE: "BACKSPACE",
        127: "BACKSPACE",
        8: "BACKSPACE",
    }
    if code in special:
        return special[code]
    return chr(code) if 32 <= code <= 126 else ""


def _init_style_attrs(*, real_curses: bool) -> dict[str, int]:
    """Configure minimal ANSI color attributes while honoring `NO_COLOR` and `TERM=dumb`."""
    attrs = {"normal": 0, "bar": 0, "header": 0, "selected": 0, "dim": 0, "user": 0, "assistant": 0}
    if not real_curses:
        return attrs
    with contextlib.suppress(curses.error):
        curses.curs_set(0)
    attrs["bar"] = curses.A_REVERSE
    attrs["selected"] = curses.A_REVERSE | curses.A_BOLD
    attrs["header"] = curses.A_BOLD
    attrs["dim"] = curses.A_DIM
    if os.environ.get("NO_COLOR") is None and os.environ.get("TERM", "").lower() != "dumb":
        with contextlib.suppress(curses.error):
            if curses.has_colors():
                curses.start_color()
                curses.use_default_colors()
                curses.init_pair(1, curses.COLOR_CYAN, -1)
                curses.init_pair(2, curses.COLOR_GREEN, -1)
                attrs["header"] = curses.color_pair(1) | curses.A_BOLD
                attrs["assistant"] = curses.color_pair(1) | curses.A_BOLD
                attrs["user"] = curses.color_pair(2) | curses.A_BOLD
    return attrs


def run_curses_browser(state: BrowserState, stdscr: CursesWindowLike | None = None) -> int:
    """Run the interactive `curses` event loop until the user presses `q`."""
    if stdscr is None:
        return int(curses.wrapper(lambda scr: run_curses_browser(state, stdscr=scr)))
    stdscr.keypad(True)
    attrs = _init_style_attrs(real_curses=isinstance(stdscr, curses.window))
    record_browser_view(source=state.source_tab, view="list")
    while True:
        height, width = stdscr.getmaxyx()
        frame = render_browser_lines(state, width=width, height=height)
        stdscr.erase()
        for row_idx, sline in enumerate(frame):
            limit = max(width - 1, 1) if row_idx == height - 1 else width
            with contextlib.suppress(curses.error):
                stdscr.addnstr(row_idx, 0, sline.text, limit, attrs.get(sline.style, 0))
        stdscr.refresh()
        token = _translate_curses_key(stdscr.getch())
        if token and state.handle_key(token, page_size=max(height - 4, 4)):
            return 0


def launch_browser(
    records: list[ConversationRecord],
    config: AppConfig,
    *,
    initial_source: str = "all",
    initial_query: str = "",
    initial_timeframe: str = "all",
    conversation_id: str = "",
) -> int:
    """Guard for an interactive TTY and launch the `curses` conversation browser."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        sys.stderr.write(
            "Error: 'wallace browse' requires an interactive TTY terminal. "
            "Use 'wallace conversation read <ID>' or 'wallace report conversations' in pipelines.\n"
        )
        return 1
    state = BrowserState(
        records=records,
        config=config,
        initial_source=initial_source,
        initial_query=initial_query,
        initial_timeframe=initial_timeframe,
        initial_conversation_id=conversation_id,
    )
    return run_curses_browser(state)
