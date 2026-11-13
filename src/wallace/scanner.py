"""Brain directory scanner resolving transcripts and SQLite sidecar metadata."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from wallace.config import AppConfig
from wallace.models import ConversationRecord, TurnUsage
from wallace.pricing import calculate_turn_cost, normalize_model_name
from wallace.protobuf import (
    RawGenTurn,
    RawTrajectoryMeta,
    extract_gen_metadata,
    extract_pbtxt_title,
    extract_trajectory_metadata,
)
from wallace.resolver import (
    DraftConversation,
    classify_conversation_role,
    dominant_model,
    resolve_feature,
    resolve_project,
    resolve_root_id,
)
from wallace.transcript_reader import TranscriptExtract, read_transcript

# region Data Models


@dataclass(slots=True)
class _SummaryEntry:
    """Intermediate row read from `conversation_summaries.db`."""

    title: str = ""
    workspace_uris: list[str] = field(default_factory=list)
    agent_name: str = ""
    parent_id: str = ""
    last_modified: str = ""


# endregion


# region Database & Transcript Readers


def _connect_readonly(db_path: Path) -> sqlite3.Connection | None:
    """Open an SQLite file in read-only mode, returning `None` if unavailable."""
    if not db_path.is_file() or db_path.stat().st_size == 0:
        return None
    try:
        return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return None


def _load_summaries_map(app_root: Path) -> dict[str, _SummaryEntry]:
    """Read `conversation_summaries.db` into a map keyed by conversation UUID."""
    conn = _connect_readonly(app_root / "conversation_summaries.db")
    if conn is None:
        return {}
    entries: dict[str, _SummaryEntry] = {}
    try:
        cursor = conn.execute(
            "SELECT conversation_id, title, workspace_uris, agent_name, "
            "parent_conversation_id, last_modified_time FROM conversation_summaries"
        )
        for cid, title, raw_uris, agent_name, parent_id, last_mod in cursor:
            entries[str(cid)] = _SummaryEntry(
                title=str(title or "").strip(),
                workspace_uris=_parse_json_str_list(str(raw_uris or "[]")),
                agent_name=str(agent_name or "").strip(),
                parent_id=str(parent_id or "").strip(),
                last_modified=str(last_mod or "").strip(),
            )
    except sqlite3.Error:
        return entries
    finally:
        conn.close()
    return entries


def _parse_json_str_list(raw: str) -> list[str]:
    """Safely parse a JSON array of strings, returning an empty list on failure."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _has_gen_tokens(decoded: RawGenTurn | None) -> bool:
    """Return `True` when `decoded` carries non-zero prompt, cache, or output tokens."""
    if decoded is None:
        return False
    return bool(decoded.input_tokens or decoded.output_tokens or decoded.cache_read_tokens)


def _read_conv_sqlite(conv_db: Path) -> tuple[list[RawGenTurn], RawTrajectoryMeta]:
    """Read `gen_metadata` turns and `trajectory_metadata_blob` from `conversations/<id>.db`."""
    conn = _connect_readonly(conv_db)
    if conn is None:
        return [], RawTrajectoryMeta()
    turns: list[RawGenTurn] = []
    traj = RawTrajectoryMeta()
    try:
        for (blob,) in conn.execute("SELECT data FROM gen_metadata ORDER BY idx ASC"):
            if isinstance(blob, bytes):
                decoded = extract_gen_metadata(blob)
                if _has_gen_tokens(decoded) and decoded is not None:
                    turns.append(decoded)
        row = conn.execute("SELECT data FROM trajectory_metadata_blob LIMIT 1").fetchone()
        if row and isinstance(row[0], bytes):
            traj = extract_trajectory_metadata(row[0])
    except sqlite3.Error:
        return turns, traj
    finally:
        conn.close()
    return turns, traj


def _build_turns_from_sqlite(
    gen_turns: list[RawGenTurn],
    turn_timestamps: list[str],
    fallback_ts: str,
    config: AppConfig,
) -> list[TurnUsage]:
    """Construct priced `TurnUsage` items from SQLite `gen_metadata` + timestamps."""
    built: list[TurnUsage] = []
    for idx, gt in enumerate(gen_turns):
        ts = turn_timestamps[idx] if idx < len(turn_timestamps) else fallback_ts
        model = normalize_model_name(gt.model)
        cost = calculate_turn_cost(
            model=model,
            input_tokens=gt.input_tokens,
            cached_input_tokens=gt.cache_read_tokens,
            output_tokens=gt.output_tokens,
            pricing_table=config.pricing,
        )
        built.append(
            TurnUsage(
                model=model,
                input_tokens=gt.input_tokens,
                cached_input_tokens=gt.cache_read_tokens,
                output_tokens=gt.output_tokens,
                thinking_tokens=gt.thinking_tokens,
                cost_usd=cost,
                created_at=ts,
            )
        )
    return built


def _load_turns_for_draft(
    transcript_path: Path,
    gen_turns: list[RawGenTurn],
    summary_ts: str,
    config: AppConfig,
) -> tuple[list[TurnUsage], TranscriptExtract, str, str]:
    """Build `(turns, transcript_extract, started_at, last_ts)` from SQLite or transcript."""
    extract = read_transcript(transcript_path, collect_token_rows=(not gen_turns))
    first_ts = extract.first_ts or summary_ts
    last_ts = extract.last_ts or summary_ts
    if gen_turns:
        turns = _build_turns_from_sqlite(gen_turns, extract.turn_timestamps, last_ts, config)
        return turns, extract, first_ts, last_ts

    turns = [
        TurnUsage(
            model=extract.model_hint,
            input_tokens=inp,
            cached_input_tokens=cached,
            output_tokens=out,
            cost_usd=calculate_turn_cost(
                model=extract.model_hint,
                input_tokens=inp,
                cached_input_tokens=cached,
                output_tokens=out,
                pricing_table=config.pricing,
            ),
            created_at=ts or summary_ts,
        )
        for inp, cached, out, ts in extract.token_rows
    ]
    return turns, extract, first_ts, last_ts


def _read_app_sidecars(
    app_root: Path | None,
    conv_id: str,
    has_summary_title: bool,
) -> tuple[list[RawGenTurn], RawTrajectoryMeta, str]:
    """Load `(gen_turns, trajectory_meta, pbtxt_title)` when `app_root` is present."""
    if app_root is None:
        return [], RawTrajectoryMeta(), ""
    gen_turns, traj = _read_conv_sqlite(app_root / "conversations" / f"{conv_id}.db")
    ann_file = app_root / "annotations" / f"{conv_id}.pbtxt"
    ann_title = ""
    if ann_file.is_file() and not has_summary_title:
        ann_title = extract_pbtxt_title(ann_file.read_text(encoding="utf-8", errors="ignore"))
    return gen_turns, traj, ann_title


# endregion


# region Project & Feature Resolution


def _dedup_nonempty(items: list[str]) -> list[str]:
    """Deduplicate non-empty strings while preserving first-seen order."""
    seen: dict[str, None] = {}
    for item in items:
        if item:
            seen.setdefault(item, None)
    return list(seen.keys())


def _resolve_cascade_links(
    summary: _SummaryEntry | None,
    gen_turns: list[RawGenTurn],
) -> tuple[str, str]:
    """Extract `(parent_id, root_id)` from `summary` and first `gen_turns` attributes."""
    parent_id = summary.parent_id if summary else ""
    root_id = ""
    if gen_turns:
        attrs = gen_turns[0].attributes
        parent_id = parent_id or attrs.get("parent_cascade_id", "")
        root_id = attrs.get("root_cascade_id", "")
    return parent_id, root_id


def _build_draft_conversation(
    *,
    conv_id: str,
    conv_brain_dir: Path,
    app_root: Path | None,
    source_label: str,
    summary: _SummaryEntry | None,
    config: AppConfig,
) -> DraftConversation | None:
    """Assemble a `DraftConversation` for a single `<brain>/<conv_id>` directory."""
    transcript_path = conv_brain_dir / ".system_generated" / "logs" / "transcript.jsonl"
    summary_title = summary.title if summary else ""
    gen_turns, traj, ann_title = _read_app_sidecars(app_root, conv_id, bool(summary_title))
    summary_ts = summary.last_modified if summary else ""
    turns, extract, started_at, last_ts = _load_turns_for_draft(
        transcript_path, gen_turns, summary_ts, config
    )
    if not turns and summary is None:
        return None

    uris = _dedup_nonempty(
        [*(summary.workspace_uris if summary else []), *traj.workspace_uris, *extract.uris]
    )
    parent_id, root_id = _resolve_cascade_links(summary, gen_turns)
    return DraftConversation(
        conversation_id=conv_id,
        source=source_label,
        title=summary_title or ann_title,
        workspace_uris=uris,
        repo_slug=traj.repo_slug,
        git_branch=traj.git_branch,
        agent_name=summary.agent_name if summary else "",
        parent_id=parent_id,
        root_id=root_id,
        started_at=started_at,
        last_timestamp=last_ts,
        initial_prompt=extract.initial_prompt,
        prompt_markers=tuple(extract.prompt_markers),
        turns=turns,
    )


# endregion


# region Scanner Entrypoints


def _scan_single_root(
    root_path: Path,
    source_label: str,
    config: AppConfig,
) -> dict[str, DraftConversation]:
    """Scan either an Antigravity app-data root or a direct `brain/` folder."""
    if not root_path.is_dir():
        return {}
    has_brain = (root_path / "brain").is_dir()
    app_root = root_path if has_brain else None
    brain_dir = (root_path / "brain") if has_brain else root_path
    summaries = _load_summaries_map(app_root) if app_root is not None else {}
    drafts: dict[str, DraftConversation] = {}

    for entry in sorted(brain_dir.iterdir()):
        if entry.is_dir() and not entry.name.startswith("."):
            draft = _build_draft_conversation(
                conv_id=entry.name,
                conv_brain_dir=entry,
                app_root=app_root,
                source_label=source_label,
                summary=summaries.get(entry.name),
                config=config,
            )
            if draft is not None:
                drafts[entry.name] = draft
    return drafts


def scan_brains(config: AppConfig) -> list[ConversationRecord]:
    """Scan all configured IDE, CLI, and standalone brain directories into records."""
    all_drafts: dict[str, DraftConversation] = {}
    if config.ide_dir is not None:
        all_drafts.update(_scan_single_root(config.ide_dir, "ide", config))
    if config.cli_dir is not None:
        all_drafts.update(_scan_single_root(config.cli_dir, "cli", config))
    for extra in config.extra_brain_dirs:
        all_drafts.update(_scan_single_root(extra, "standalone", config))

    wp_regex = re.compile(config.work_package_pattern)
    ignored = {b.strip() for b in config.ignored_branches}
    records: list[ConversationRecord] = []

    for cid, draft in all_drafts.items():
        if not draft.turns:
            continue
        resolved_root_id = draft.root_id or resolve_root_id(cid, all_drafts)
        root_draft = all_drafts.get(resolved_root_id, draft)
        records.append(
            ConversationRecord(
                conversation_id=cid,
                source=draft.source,
                project=resolve_project(draft, root_draft),
                feature=resolve_feature(draft, root_draft, wp_regex, ignored),
                title=draft.title or draft.agent_name or f"conv-{cid[:8]}",
                parent_conversation_id=draft.parent_id,
                root_conversation_id=resolved_root_id,
                agent_name=draft.agent_name,
                git_branch=draft.git_branch,
                role=classify_conversation_role(draft),
                primary_model=dominant_model(draft.turns),
                started_at=draft.started_at,
                last_timestamp=draft.last_timestamp,
                turns=draft.turns,
                prompt_markers=draft.prompt_markers,
            )
        )
    records.sort(key=lambda r: (r.project, r.feature, r.conversation_id))
    return records


# endregion
