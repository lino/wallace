"""Behavioural tests for multi-provider message loading, `conversation read`, and TUI browser."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest

from test_claude_and_grok_providers import _build_claude_fixture, _build_grok_fixture
from wallace.browser import BrowserState, render_browser_lines, run_curses_browser
from wallace.cli import main
from wallace.config import AppConfig
from wallace.message_loader import load_conversation_messages
from wallace.scanner import scan_brains


def test_load_messages_across_agy_claude_and_grok(
    sample_env: dict[str, Path],
    tmp_path: Path,
) -> None:
    """`load_conversation_messages` normalizes AGY, Claude, and Grok transcripts cleanly."""
    claude_dir = _build_claude_fixture(tmp_path)
    grok_dir = _build_grok_fixture(tmp_path)
    cfg = AppConfig(
        ide_dir=sample_env["ide"],
        cli_dir=sample_env["cli"],
        claude_dir=claude_dir,
        grok_dir=grok_dir,
    )
    records = scan_brains(cfg)
    by_id = {r.conversation_id: r for r in records}

    # 1. AGY IDE transcript unwraps <USER_REQUEST> cleanly
    agy_msgs = load_conversation_messages(by_id["11111111-1111-4111-8111-111111111111"], cfg)
    assert any(m.role == "user" and "Build OAuth login" in m.content for m in agy_msgs)
    assert any(m.role == "assistant" and m.tokens == 17_000 for m in agy_msgs)

    # 2. Claude Code JSONL deduplicates msg_01_shared into one assistant message with thinking/tools
    claude_msgs = load_conversation_messages(by_id["c1111111-1111-4111-8111-111111111111"], cfg)
    assert [m.role for m in claude_msgs] == ["user", "assistant"]
    assert "ALPHA-WP-12" in claude_msgs[0].content
    assert "updated parser" in claude_msgs[1].content
    assert "Inspecting schema first." in claude_msgs[1].thinking
    assert "Edit(" in claude_msgs[1].tool_summary
    assert claude_msgs[1].tokens == 5750

    # 3. Grok chat_history.jsonl skips synthetic_reason reminders and attaches reasoning summary
    grok_msgs = load_conversation_messages(by_id["01a1db64-4936-7472-992c-3ebd4c062570"], cfg)
    user_msgs = [m for m in grok_msgs if m.role == "user"]
    assert len(user_msgs) == 1
    assert "GAMMA-WP-03" in user_msgs[0].content
    asst_msgs = [m for m in grok_msgs if m.role == "assistant"]
    assert len(asst_msgs) == 1
    assert "Designing state machine." in asst_msgs[0].thinking
    assert "Implemented the streaming parser" in asst_msgs[0].content


def test_cli_conversation_read_and_all_schemas_zero_drift(
    sample_env: dict[str, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`wallace conversation read` emits readable text and schema-validated JSON across sources."""
    claude_dir = _build_claude_fixture(tmp_path)
    grok_dir = _build_grok_fixture(tmp_path)
    monkeypatch.setenv("WALLACE_IDE_DIR", str(sample_env["ide"]))
    monkeypatch.setenv("WALLACE_CLI_DIR", str(sample_env["cli"]))
    monkeypatch.setenv("WALLACE_CLAUDE_DIR", str(claude_dir))
    monkeypatch.setenv("WALLACE_GROK_DIR", str(grok_dir))
    repo_root = Path(__file__).resolve().parents[1]

    # Zero-drift check across all 5 JSON Schemas
    assert main(["schema", "--list"]) == 0
    schema_names = [s.strip() for s in capsys.readouterr().out.splitlines() if s.strip()]
    assert "conversation-messages" in schema_names
    for name in schema_names:
        assert main(["schema", name, "--format", "json-schema"]) == 0
        runtime = capsys.readouterr().out
        committed = (repo_root / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8")
        assert runtime == committed

    # Read Grok conversation as JSON and validate against conversation-messages.schema.json
    assert main(["conversation", "read", "01a1db64", "--format", "json"]) == 0
    raw_json = capsys.readouterr().out
    msg_schema = json.loads(
        (repo_root / "schemas" / "conversation-messages.schema.json").read_text(encoding="utf-8")
    )
    parsed = json.loads(raw_json)
    jsonschema.validate(instance=parsed, schema=msg_schema)
    assert parsed["source"] == "grok"
    assert len(parsed["messages"]) >= 2

    # Read Claude conversation as readable text/markdown
    assert main(["conversation", "read", "c1111111"]) == 0
    text_out = capsys.readouterr().out
    assert "Auth Refactor Session" in text_out
    assert "updated parser" in text_out

    # CLI flag overrides --claude-dir and --grok-dir work on `wallace report`
    assert (
        main(
            [
                "report",
                "sources",
                "--claude-dir",
                str(claude_dir),
                "--grok-dir",
                str(grok_dir),
                "--format",
                "json",
            ]
        )
        == 0
    )
    rep_json = json.loads(capsys.readouterr().out)
    sources_seen = {b["source"] for b in rep_json["buckets"]}
    assert {"ide", "cli", "claude", "grok"} <= sources_seen

    # `wallace conversation list --source claude` and Prometheus browser counter
    assert main(["conversation", "list", "--source", "claude", "--format", "json"]) == 0
    claude_list = json.loads(capsys.readouterr().out)
    assert all(b["source"] == "claude" for b in claude_list["buckets"])

    assert main(["metrics", "export"]) == 0
    prom_text = capsys.readouterr().out
    assert "wallace_browser_views_total" in prom_text

    # Exported Claude `.json` conversation archive scans & reads with estimated tokens
    export_json = claude_dir / "conversations_export.json"
    export_json.write_text(
        json.dumps(
            [
                {
                    "uuid": "e9999999-9999-4999-8999-999999999999",
                    "name": "Web Exported Claude Chat",
                    "created_at": "2026-11-14T12:00:00Z",
                    "chat_messages": [
                        {"sender": "human", "text": "Summarize ALPHA-WP-99."},
                        {
                            "sender": "assistant",
                            "text": "ALPHA-WP-99 adds multi-provider browsing.",
                        },
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )
    assert main(["conversation", "read", "e9999999"]) == 0
    exp_out = capsys.readouterr().out
    assert "Web Exported Claude Chat" in exp_out
    assert "ALPHA-WP-99 adds multi-provider browsing." in exp_out


def test_browse_non_tty_guard(
    sample_env: dict[str, Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`wallace browse` refuses to block in non-TTY pipelines and prints actionable guidance."""
    monkeypatch.setenv("WALLACE_IDE_DIR", str(sample_env["ide"]))
    monkeypatch.setenv("WALLACE_CLI_DIR", str(sample_env["cli"]))
    rc = main(["browse"])
    assert rc == 1
    err = capsys.readouterr().err.lower()
    assert "tty" in err
    assert "conversation" in err


def test_tui_browser_state_navigation_tabs_search_and_80x24_geometry(
    sample_env: dict[str, Path],
    tmp_path: Path,
) -> None:
    """TUI state machine supports tabs, search, sorting, detail view, ledger view, and 80x24."""
    claude_dir = _build_claude_fixture(tmp_path)
    grok_dir = _build_grok_fixture(tmp_path)
    cfg = AppConfig(
        ide_dir=sample_env["ide"],
        cli_dir=sample_env["cli"],
        claude_dir=claude_dir,
        grok_dir=grok_dir,
    )
    records = scan_brains(cfg)
    state = BrowserState(records=records, config=cfg)

    # Render initial list at minimum 80x24 terminal geometry
    lines_80 = render_browser_lines(state, width=80, height=24)
    assert len(lines_80) == 24
    assert all(len(row.text) <= 80 for row in lines_80)
    assert "WALLACE" in lines_80[0].text
    assert "Enter:Open" in lines_80[-1].text

    # Cycle provider tabs: All -> AGY -> Claude -> Grok
    state.handle_key("TAB")
    assert state.source_tab == "agy"
    assert all(r.source in ("ide", "cli", "standalone") for r in state.visible_records)

    state.handle_key("TAB")
    assert state.source_tab == "claude"
    assert all(r.source == "claude" for r in state.visible_records)
    # Estimated conversation displays `~` token marker in wide list
    claude_lines = render_browser_lines(state, width=110, height=24)
    assert any("~" in row.text for row in claude_lines)

    state.handle_key("TAB")
    assert state.source_tab == "grok"
    assert all(r.source == "grok" for r in state.visible_records)

    # Reset to All ('1') and filter via '/'
    state.handle_key("1")
    assert state.source_tab == "all"
    state.handle_key("/")
    for ch in "GAMMA-WP-03":
        state.handle_key(ch)
    state.handle_key("ENTER")
    assert len(state.visible_records) == 1
    assert state.visible_records[0].source == "grok"

    # Sort cycling ('s')
    state.handle_key("s")
    assert state.sort_mode in ("tokens", "cost", "recent")

    # Open conversation detail ('ENTER'), toggle tools/thinking ('t'), switch to turns ('v')
    state.handle_key("ENTER")
    assert state.mode == "detail"
    detail_compact = "\n".join(r.text for r in render_browser_lines(state, width=90, height=24))
    assert "Implemented the streaming parser" in detail_compact

    state.handle_key("t")
    assert state.show_details is True
    detail_expanded = "\n".join(r.text for r in render_browser_lines(state, width=90, height=24))
    assert "Designing state machine." in detail_expanded

    state.handle_key("v")
    assert state.detail_subview == "turns"
    turns_view = "\n".join(r.text for r in render_browser_lines(state, width=90, height=24))
    assert "grok-4.7-build" in turns_view
    assert "124,000" in turns_view

    # Toggle '?' help overlay and close it
    state.handle_key("?")
    assert state.show_help is True
    help_view = "\n".join(r.text for r in render_browser_lines(state, width=80, height=24))
    assert "KEYBINDINGS" in help_view.upper()
    state.handle_key("ESC")
    assert state.show_help is False

    # Back to list ('ESC') and quit ('q')
    state.handle_key("ESC")
    assert state.mode == "list"
    should_quit = state.handle_key("q")
    assert should_quit is True


class _FakeWindow:
    """Minimal fake `curses` window recording drawn lines and feeding scripted keys."""

    def __init__(self, keys: list[int], height: int = 24, width: int = 90) -> None:
        self._keys = list(keys)
        self._height = height
        self._width = width
        self.drawn: list[str] = []

    def keypad(self, flag: bool) -> None:
        """Accept keypad mode toggle."""

    def erase(self) -> None:
        """Clear recorded buffer for next frame."""
        self.drawn.clear()

    def refresh(self) -> None:
        """No-op refresh."""

    def getmaxyx(self) -> tuple[int, int]:
        """Return `(height, width)`."""
        return self._height, self._width

    def addnstr(self, y: int, x: int, text: str, n: int, attr: int = 0) -> None:
        """Record up to `n` characters drawn at `(y, x)`."""
        self.drawn.append(text[:n])

    def getch(self) -> int:
        """Pop next scripted keycode or `'q'` when exhausted."""
        return self._keys.pop(0) if self._keys else ord("q")


def test_curses_driver_loop_executes_cleanly(
    sample_env: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`run_curses_browser` paints frames and exits cleanly on scripted key sequence."""
    monkeypatch.setenv("NO_COLOR", "1")
    cfg = AppConfig(ide_dir=sample_env["ide"], cli_dir=sample_env["cli"])
    records = scan_brains(cfg)
    state = BrowserState(records=records, config=cfg)
    fake_win = _FakeWindow(
        keys=[ord("\t"), ord("j"), ord("\n"), ord("v"), 27, ord("q")],
        height=24,
        width=80,
    )
    rc = run_curses_browser(state, stdscr=fake_win)
    assert rc == 0
    assert any("WALLACE" in line for line in fake_win.drawn)


def test_tui_browser_timeframe_cycling_and_initial_timeframe(
    sample_env: dict[str, Path],
) -> None:
    """`BrowserState` supports initial `--timeframe` and `t` cycling in list mode."""
    cfg = AppConfig(ide_dir=sample_env["ide"], cli_dir=sample_env["cli"])
    records = scan_brains(cfg)
    ref_now = datetime(2026, 11, 13, 12, 0, 0, tzinfo=UTC)

    state = BrowserState(
        records=records,
        config=cfg,
        initial_timeframe="yesterday",
        now=ref_now,
    )
    assert state.timeframe == "yesterday"
    assert all(r.project == "beta-engine" for r in state.visible_records)
    frame_80 = render_browser_lines(state, width=80, height=24)
    assert len(frame_80) == 24
    assert all(len(row.text) <= 80 for row in frame_80)
    assert "tf:yesterday" in render_browser_lines(state, width=120, height=24)[0].text

    # Pressing 't' in list mode cycles timeframes through presets back to 'all'
    seen_timeframes = {state.timeframe}
    for _ in range(8):
        state.handle_key("t")
        seen_timeframes.add(state.timeframe)
    assert {"all", "today", "yesterday", "7d", "30d"} <= seen_timeframes
