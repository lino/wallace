"""Project slug, parent cascade root, role, and Work Package / feature resolution helpers."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

from wallace.config import DEFAULT_WP_REGEX
from wallace.models import PromptMarker, TurnUsage

# region Constants & Defaults

_WORKTREE_MARKER = "/worktrees/"
_DEFAULT_WP_PATTERN = re.compile(DEFAULT_WP_REGEX)
_GENERIC_ROLE_PREFIX_RE = re.compile(r"(?i)^(?:SUBAGENT|WORKER|QA|AUDITOR|REVIEWER|VERIFIER)$")
_CANONICAL_WP_PARTS_RE = re.compile(r"(?i)^(?:([A-Z][A-Z0-9]+)-)?WP-?(\d+)$")
_BARE_WP_RE = re.compile(r"(?i)\bWP-?(\d+)\b")
_WP_NUM_NORMALIZE_RE = re.compile(r"(?i)^WP-?(\d+)$")
_QA_TOKEN_RE = re.compile(r"(?i)(?:^|[-_\s@/])(qa|auditor|verifier|reviewer)(?:$|[-_\s\d/])")
_QA_BRIEF_RE = re.compile(
    r"(?i)(?:#\s*adversarial\s+qa|\bqa\s+auditor\b|audit\s+the\s+candidate\s+changes)"
)
_OPENING_PROMPT_SLICE = 600

# endregion


# region Data Models


@dataclass(slots=True)
class DraftConversation:
    """Unresolved conversation assembled before parent-tree project/feature propagation.

    Attributes:
        conversation_id: Conversation UUID directory name.
        source: Origin application (`"ide"`, `"cli"`, or `"standalone"`).
        title: Human-readable conversation title.
        workspace_uris: Ordered `file://` workspace URIs collected across sidecars.
        repo_slug: Optional `owner/repo` slug from trajectory metadata.
        git_branch: Optional git branch name from trajectory metadata.
        agent_name: Optional subagent role or swarm worker name.
        parent_id: Immediate parent conversation UUID if subagent.
        root_id: Explicit root cascade UUID if recorded.
        started_at: Earliest ISO-8601 timestamp.
        last_timestamp: Latest ISO-8601 timestamp.
        initial_prompt: Initial user or worker assignment brief extracted from transcript.
        prompt_markers: Chronological prompt/board markers referencing task IDs.
        turns: Ordered `TurnUsage` list.
        transcript_path: Optional path to the on-disk transcript file or session directory.
    """

    conversation_id: str
    source: str
    title: str = ""
    workspace_uris: list[str] = field(default_factory=list)
    repo_slug: str = ""
    git_branch: str = ""
    agent_name: str = ""
    parent_id: str = ""
    root_id: str = ""
    started_at: str = ""
    last_timestamp: str = ""
    initial_prompt: str = ""
    prompt_markers: tuple[PromptMarker, ...] = ()
    turns: list[TurnUsage] = field(default_factory=list)
    transcript_path: Path | None = None


# endregion


# region Project & Feature Resolution


def extract_project_from_uri(uri: str) -> str:
    """Derive a clean project folder slug from a `file://` URI, skipping worktrees."""
    if not uri or _WORKTREE_MARKER in uri or "/.gemini/" in uri:
        return ""
    parsed = urlparse(uri)
    raw_path = unquote(parsed.path if parsed.scheme == "file" else uri)
    path_obj = Path(raw_path)
    parts = path_obj.parts
    if "Projects" in parts:
        idx = parts.index("Projects")
        if idx + 1 < len(parts):
            candidate = parts[idx + 1]
            if candidate == "private" and idx + 2 < len(parts):
                return parts[idx + 2]
            return candidate
    return path_obj.parent.name if path_obj.suffix else path_obj.name


def resolve_root_id(cid: str, drafts: dict[str, DraftConversation]) -> str:
    """Walk `parent_id` links without cycles to find the top-level conversation UUID."""
    seen: set[str] = set()
    curr = cid
    while curr in drafts and curr not in seen:
        seen.add(curr)
        nxt = _next_parent_candidate(drafts[curr])
        if not nxt or nxt == curr:
            return curr
        if nxt not in drafts:
            return nxt if not drafts[curr].root_id else curr
        curr = nxt
    return curr


def _next_parent_candidate(draft: DraftConversation) -> str:
    """Return the immediate parent or explicit root UUID for `draft`."""
    return draft.parent_id or draft.root_id


def normalize_wp_token(raw_wp: str) -> str:
    """Canonicalize Work Package tokens (`wp15` -> `WP-15`, `beta-wp-7` -> `BETA-WP-07`)."""
    cleaned = raw_wp.strip()
    parts_match = _CANONICAL_WP_PARTS_RE.fullmatch(cleaned)
    if parts_match:
        prefix = parts_match.group(1)
        num = int(parts_match.group(2))
        if (
            prefix
            and _DEFAULT_WP_PATTERN.fullmatch(cleaned)
            and not _GENERIC_ROLE_PREFIX_RE.fullmatch(prefix)
        ):
            return f"{prefix.upper()}-WP-{num:02d}"
        return f"WP-{num:02d}"
    return cleaned.upper()


def extract_prefixed_wp_tokens(
    text: str,
    wp_regex: re.Pattern[str] = _DEFAULT_WP_PATTERN,
) -> tuple[str, ...]:
    """Extract ordered distinct canonical `<PROJECT>-WP-<NN>` tokens from `text`."""
    if not text:
        return ()
    seen: dict[str, None] = {}
    for match in wp_regex.finditer(text):
        raw = match.group(1) if match.lastindex else match.group(0)
        canonical = normalize_wp_token(raw)
        if "-WP-" in canonical:
            seen.setdefault(canonical, None)
    return tuple(seen.keys())


def classify_conversation_role(draft: DraftConversation) -> str:
    """Classify a conversation as `'qa'` or `'implementation'` from metadata and brief."""
    for label in (draft.agent_name, draft.title, draft.git_branch):
        if label and _QA_TOKEN_RE.search(label):
            return "qa"
    opening = draft.initial_prompt[:_OPENING_PROMPT_SLICE]
    if opening and _QA_BRIEF_RE.search(opening):
        return "qa"
    return "implementation"


def _scan_header_wp(
    draft: DraftConversation,
    wp_regex: re.Pattern[str],
) -> tuple[str, str, int]:
    """Scan `git_branch`, `agent_name`, and `title` for `(prefixed_wp, bare_wp, bare_num)`."""
    bare_wp = ""
    bare_num = -1
    for candidate_text in (draft.git_branch, draft.agent_name, draft.title):
        if not candidate_text:
            continue
        prefixed = extract_prefixed_wp_tokens(candidate_text, wp_regex)
        if prefixed:
            return prefixed[0], "", -1
        if not bare_wp:
            wp_match = wp_regex.search(candidate_text) or _BARE_WP_RE.search(candidate_text)
            if wp_match:
                raw = wp_match.group(1) if wp_match.lastindex else wp_match.group(0)
                normalized = normalize_wp_token(raw)
                tail = _WP_NUM_NORMALIZE_RE.match(normalized)
                bare_wp = normalized
                bare_num = int(tail.group(1)) if tail else -1
    return "", bare_wp, bare_num


def _upgrade_bare_wp(
    prompt: str,
    wp_regex: re.Pattern[str],
    bare_wp: str,
    bare_num: int,
) -> str:
    """Upgrade `bare_wp` to `<PROJECT>-WP-<NN>` when `prompt` mentions a matching number."""
    for canonical in extract_prefixed_wp_tokens(prompt, wp_regex):
        _, _, tail_num = canonical.rpartition("-WP-")
        if tail_num.isdigit() and int(tail_num) == bare_num:
            return canonical
    return bare_wp


def _resolve_wp_from_prompt(
    draft: DraftConversation,
    wp_regex: re.Pattern[str],
    bare_wp: str,
    bare_num: int,
) -> str:
    """Upgrade `bare_wp` or extract a single task ID from `draft.initial_prompt`."""
    if bare_wp:
        return _upgrade_bare_wp(draft.initial_prompt, wp_regex, bare_wp, bare_num)

    opening = draft.initial_prompt[:_OPENING_PROMPT_SLICE]
    if not opening:
        return ""
    prefixed = extract_prefixed_wp_tokens(opening, wp_regex)
    if classify_conversation_role(draft) == "qa" and len(prefixed) >= 2:
        return ""
    if prefixed:
        return prefixed[0]
    wp_match = wp_regex.search(opening)
    if not wp_match:
        return ""
    raw = wp_match.group(1) if wp_match.lastindex else wp_match.group(0)
    return normalize_wp_token(raw)


def resolve_feature(
    draft: DraftConversation,
    root_draft: DraftConversation,
    wp_regex: re.Pattern[str],
    ignored_branches: set[str],
) -> str:
    """Resolve feature name via `<PROJECT>-WP-<NN>` -> prompt brief -> git branch -> title."""
    prefixed_wp, bare_wp, bare_num = _scan_header_wp(draft, wp_regex)
    if prefixed_wp:
        return prefixed_wp
    prompt_wp = _resolve_wp_from_prompt(draft, wp_regex, bare_wp, bare_num)
    if prompt_wp:
        return prompt_wp
    return _fallback_branch_or_title(draft, root_draft, ignored_branches)


def _fallback_branch_or_title(
    draft: DraftConversation,
    root_draft: DraftConversation,
    ignored_branches: set[str],
) -> str:
    """Return the first non-ignored git branch, or fall back to root/draft conversation title."""
    for raw_branch in (draft.git_branch, root_draft.git_branch):
        branch = raw_branch.strip()
        if branch and branch not in ignored_branches and not branch.startswith("subagent-"):
            return branch
    return root_draft.title or draft.title or f"conv-{root_draft.conversation_id[:8]}"


def resolve_project(draft: DraftConversation, root_draft: DraftConversation) -> str:
    """Resolve project slug from direct workspace URIs, git repo slug, or root parent."""
    for target in (draft, root_draft):
        for uri in target.workspace_uris:
            slug = extract_project_from_uri(uri)
            if slug:
                return slug
        if target.repo_slug:
            return target.repo_slug.split("/")[-1]
    return "unassigned"


def dominant_model(turns: list[TurnUsage]) -> str:
    """Return the model accounting for the largest share of tokens in `turns`."""
    if not turns:
        return "unknown"
    totals: Counter[str] = Counter()
    for turn in turns:
        totals[turn.model] += max(turn.total_tokens, 1)
    return totals.most_common(1)[0][0]


# endregion
