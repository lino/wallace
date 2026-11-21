"""Single-viewport terminal frame layout (`80x24` safe) for `wallace browse`."""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from typing import TYPE_CHECKING

from wallace.models import ConversationMessage, ConversationRecord, display_cost

if TYPE_CHECKING:
    from wallace.browser import BrowserState

SOURCE_TABS: tuple[str, ...] = ("all", "agy", "claude", "grok", "codex")
TAB_LABELS: dict[str, str] = {
    "all": "All",
    "agy": "AGY",
    "claude": "Claude",
    "grok": "Grok",
    "codex": "Codex",
}


@dataclass(frozen=True, slots=True)
class StyledLine:
    """Single terminal line paired with a logical style token."""

    text: str
    style: str = "normal"


def _clip(text: str, width: int) -> str:
    """Truncate `text` cleanly so it never exceeds `width` columns."""
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    return (text[: width - 1] + "…") if width >= 2 else text[:width]


def _render_top_bar(state: BrowserState, width: int) -> StyledLine:
    """Render the single-line top status bar with provider tabs and filtered spend totals."""
    tabs = " ".join(
        f"[{TAB_LABELS[t]}]" if t == state.source_tab else f" {TAB_LABELS[t]} " for t in SOURCE_TABS
    )
    vis = state.visible_records
    tok = sum(r.total_tokens for r in vis)
    cost = sum(r.cost_usd for r in vis)
    tf = f" · tf:{state.timeframe}" if state.timeframe != "all" else ""
    flt = f" /{state.filter_query}" if state.filter_query else ""
    summary = (
        f"{len(vis)} conv · {tok:,} tok · {display_cost(cost, 2)} · sort:{state.sort_mode}{tf}{flt}"
    )
    left = f"WALLACE {tabs}"
    gap = max(width - len(left) - len(summary), 2)
    fits = len(left) + 2 + len(summary) <= width
    combined = f"{left}{' ' * gap}{summary}" if fits else f"{left}  {summary}"
    return StyledLine(_clip(combined, width).ljust(width), "bar")


def _render_bottom_bar(state: BrowserState, width: int) -> StyledLine:
    """Render the context-sensitive single-line footer shortcut or search bar."""
    if state.input_mode:
        prompt = f"Filter: {state.filter_query}▌  (Enter:Apply  Esc:Clear)"
        return StyledLine(_clip(prompt, width).ljust(width), "bar")
    if state.show_help:
        hint = "?:Close  Esc:Close  Enter:Close"
    elif state.mode == "detail":
        det = "HideTools" if state.show_details else "ShowTools"
        sub = "Messages" if state.detail_subview == "turns" else "Turns"
        hint = f"j/k:Scroll  t:{det}  v:{sub}  Esc:Back  ?:Help  q:Quit"
    else:
        hint = "Tab/1-4:Src  /:Filter  t:Time  s:Sort  Enter:Open  ?:Help  q:Quit"
    return StyledLine(_clip(hint, width).ljust(width), "bar")


def _format_list_row(rec: ConversationRecord, width: int, *, is_header: bool = False) -> str:
    """Format either the column header or one conversation row to fit `width`."""
    est_mark = "~" if (not is_header and rec.has_estimated_tokens) else ""
    tok_s = "TOKENS" if is_header else f"{est_mark}{rec.total_tokens:,}"
    cost_s = "COST" if is_header else display_cost(rec.cost_usd, 3)
    src_s = "SRC" if is_header else rec.source[:6]
    if width >= 98:
        proj_s = "PROJECT" if is_header else _clip(rec.project, 15)
        feat_s = "FEATURE" if is_header else _clip(rec.feature, 15)
        mod_s = "MODEL" if is_header else _clip(rec.primary_model, 16)
        rem = max(width - (6 + 15 + 15 + 16 + 11 + 9 + 12), 10)
        title_s = "TITLE" if is_header else _clip(rec.title, rem)
        return (
            f"{src_s:<6}  {proj_s:<15}  {feat_s:<15}  {title_s:<{rem}}  "
            f"{mod_s:<16}  {tok_s:>11}  {cost_s:>9}"
        )[:width]
    ctx_raw = "PROJECT/FEATURE" if is_header else f"{rec.project}/{rec.feature}"
    ctx_s = _clip(ctx_raw, 20)
    rem = max(width - (6 + 20 + 11 + 8 + 8), 8)
    title_s = "TITLE" if is_header else _clip(rec.title, rem)
    return f"{src_s:<6}  {ctx_s:<20}  {title_s:<{rem}}  {tok_s:>11}  {cost_s:>8}"[:width]


def _render_list_body(state: BrowserState, width: int, body_h: int) -> list[StyledLine]:
    """Render the single-viewport conversation list body."""
    vis = state.visible_records
    hdr_stub = ConversationRecord("", "", "", "", "")
    rows = [StyledLine(_format_list_row(hdr_stub, width, is_header=True), "header")]
    avail = max(body_h - 1, 1)
    if not vis:
        rows.append(StyledLine(_clip("  No conversations match active filters.", width), "dim"))
        return rows
    sel = min(max(state.selected_index, 0), len(vis) - 1)
    start = min(max(state.list_scroll, 0), max(len(vis) - avail, 0))
    start = min(start, sel)
    if sel >= start + avail:
        start = sel - avail + 1
    for idx in range(start, min(start + avail, len(vis))):
        line = _format_list_row(vis[idx], width)
        style = "selected" if idx == sel else "normal"
        rows.append(StyledLine(line.ljust(width) if idx == sel else line, style))
    return rows


def _build_detail_lines(
    state: BrowserState, rec: ConversationRecord, width: int
) -> list[StyledLine]:
    """Build wrapped content lines for either the transcript or turns subview."""
    wrap_w = max(width - 2, 20)
    if state.detail_subview == "turns":
        hdr = "  #  TIMESTAMP             MODEL                  TOKENS        COST"
        out = [StyledLine(_clip(hdr, width), "header")]
        for idx, t in enumerate(rec.turns, start=1):
            est = "~" if t.is_estimated else ""
            row = (
                f"{idx:>3}  {t.created_at[:19]:<19}  {_clip(t.model, 20):<20}  "
                f"{est + format(t.total_tokens, ','):>10}  {display_cost(t.cost_usd):>10}"
            )
            out.append(StyledLine(_clip(row, width), "normal"))
        return out
    msgs = state.active_messages()
    if not msgs:
        empty = "  (No transcript messages recorded; press 'v' for turns.)"
        return [StyledLine(_clip(empty, width), "dim")]
    lines: list[StyledLine] = []
    for msg in msgs:
        lines.extend(_format_message_block(msg, width, wrap_w, show_details=state.show_details))
    return lines


def _format_message_block(
    msg: ConversationMessage, width: int, wrap_w: int, *, show_details: bool
) -> list[StyledLine]:
    """Wrap one `ConversationMessage` into styled viewport lines."""
    if msg.role == "tool" and not show_details:
        return [StyledLine(_clip(f"  [tool] {msg.content}", width), "dim")]
    meta = [p for p in (msg.created_at[:19], msg.model) if p]
    if msg.tokens:
        meta.append(f"{'~' if msg.is_estimated else ''}{msg.tokens:,} tok")
    rstyle = "user" if msg.role == "user" else ("assistant" if msg.role == "assistant" else "dim")
    block = [StyledLine(_clip(f"[{msg.role.upper()}] {' · '.join(meta)}".strip(), width), rstyle)]
    if msg.thinking:
        if show_details:
            for wline in textwrap.wrap(f"[thinking] {msg.thinking}", width=wrap_w):
                block.append(StyledLine(_clip(f"  {wline}", width), "dim"))
        else:
            block.append(StyledLine(_clip("  [thinking — press 't' to expand]", width), "dim"))
    if msg.tool_summary and msg.role != "tool":
        prefix = f"[tools] {msg.tool_summary}"
        wrapped_tools = textwrap.wrap(prefix, width=wrap_w) if show_details else [prefix]
        for wline in wrapped_tools:
            block.append(StyledLine(_clip(f"  {wline}", width), "dim"))
    for para in msg.content.splitlines() if msg.content else []:
        for wline in textwrap.wrap(para, width=wrap_w) or [""]:
            block.append(StyledLine(_clip(f"  {wline}", width), "normal"))
    block.append(StyledLine("", "normal"))
    return block


def _render_detail_body(state: BrowserState, width: int, body_h: int) -> list[StyledLine]:
    """Render conversation metadata header + scrolled detail lines."""
    rec = state.active_record()
    if rec is None:
        return [StyledLine(_clip("No conversation selected.", width), "dim")]
    est = "~" if rec.has_estimated_tokens else ""
    hdr1 = _clip(f"[{rec.source}] {rec.title} ({rec.conversation_id[:12]})", width)
    hdr2 = _clip(
        f"{rec.project} / {rec.feature} · {rec.primary_model} · "
        f"{rec.turn_count} turns · {est}{rec.total_tokens:,} tok · {display_cost(rec.cost_usd)}",
        width,
    )
    content = _build_detail_lines(state, rec, width)
    avail = max(body_h - 2, 1)
    state.detail_scroll = min(max(state.detail_scroll, 0), max(len(content) - avail, 0))
    return [
        StyledLine(hdr1, "header"),
        StyledLine(hdr2, "dim"),
        *content[state.detail_scroll : state.detail_scroll + avail],
    ]


def _render_help_body(width: int) -> list[StyledLine]:
    """Render the modal `?` keybindings reference sheet."""
    entries = [
        ("KEYBINDINGS — WALLACE CONVERSATION BROWSER", "header"),
        ("", "normal"),
        ("  Tab / Shift-Tab    Cycle provider tabs (All, AGY, Claude, Grok, Codex)", "normal"),
        ("  1 / 2 / 3 / 4 / 5  Jump to All / AGY / Claude / Grok / Codex", "normal"),
        ("  /                  Filter by project, feature, title, model, or ID", "normal"),
        ("  t (list)           Cycle timeframe (all, today, yesterday, 7d, 30d, month)", "normal"),
        ("  s                  Cycle sort order (recent, tokens, cost)", "normal"),
        ("  j / k / Up / Down  Move selection or scroll transcript", "normal"),
        ("  PgDn / PgUp / g/G  Page down/up or jump to start/end", "normal"),
        ("  Enter / l / Right  Open selected conversation transcript", "normal"),
        ("  t (detail)         Toggle expanded thinking & tool call details", "normal"),
        ("  v                  Toggle Messages vs Turn-by-Turn token ledger", "normal"),
        ("  Esc / h / Left     Close overlay or return to conversation list", "normal"),
        ("  q                  Quit browser", "normal"),
    ]
    return [StyledLine(_clip(txt, width), st) for txt, st in entries]


def render_browser_lines(
    state: BrowserState, width: int = 100, height: int = 24
) -> list[StyledLine]:
    """Render a complete `width x height` terminal frame of `StyledLine` rows."""
    eff_w, eff_h = max(width, 40), max(height, 6)
    body_h = eff_h - 2
    if state.show_help:
        body = _render_help_body(eff_w)[:body_h]
    elif state.mode == "detail":
        body = _render_detail_body(state, eff_w, body_h)[:body_h]
    else:
        body = _render_list_body(state, eff_w, body_h)[:body_h]
    while len(body) < body_h:
        body.append(StyledLine("", "normal"))
    return [_render_top_bar(state, eff_w), *body, _render_bottom_bar(state, eff_w)]
