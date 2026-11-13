"""JSON Schema Draft 2020-12 and W3C CSVW contracts for Wallace exports and queries."""

from __future__ import annotations

import json

SCHEMA_NAMES: tuple[str, ...] = (
    "token-report",
    "ledger-row",
    "conversation-usage",
    "task-usage",
)
CSV_COLUMN_ORDER: tuple[str, ...] = (
    "period",
    "period_start",
    "source",
    "project",
    "feature",
    "conversation_id",
    "title",
    "model",
    "conversation_count",
    "turn_count",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "thinking_tokens",
    "total_tokens",
    "cost_usd",
)
BUCKET_REQUIRED_FIELDS: tuple[str, ...] = (
    "period",
    "period_start",
    "source",
    "project",
    "feature",
    "conversation_id",
    "conversation_ids",
    "title",
    "model",
    "conversation_count",
    "turn_count",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "thinking_tokens",
    "total_tokens",
    "cost_usd",
)


def _str_prop(description: str, enum: list[str] | None = None) -> dict[str, object]:
    """Build a string JSON Schema property descriptor."""
    prop: dict[str, object] = {"type": "string", "description": description}
    if enum is not None:
        prop["enum"] = enum
    return prop


def _nonneg_int(description: str, minimum: int = 0) -> dict[str, object]:
    """Build a bounded integer JSON Schema property descriptor."""
    return {"type": "integer", "minimum": minimum, "description": description}


def _nonneg_num(description: str, maximum: float | None = None) -> dict[str, object]:
    """Build a non-negative number JSON Schema property descriptor."""
    prop: dict[str, object] = {"type": "number", "minimum": 0.0, "description": description}
    if maximum is not None:
        prop["maximum"] = maximum
    return prop


def _ledger_row_properties() -> dict[str, object]:
    """Return flat scalar JSON Schema properties for `jsonl` VisiData stream rows."""
    return {
        "period": _str_prop(
            "Timeframe bucket label (YYYY-MM-DD, YYYY-Www, YYYY-MM, interval, or '*')."
        ),
        "period_start": _str_prop(
            "ISO-8601 start date or timestamp of the timeframe bucket, or empty string."
        ),
        "source": _str_prop(
            "Origin environment (ide, cli, standalone, mixed, or none).",
            enum=["ide", "cli", "standalone", "mixed", "none"],
        ),
        "project": _str_prop("Resolved project name or '*' when aggregated across projects."),
        "feature": _str_prop("Resolved Work Package, git branch, root title, or '*'."),
        "conversation_id": _str_prop(
            "Conversation UUID when grouped by conversation, else empty string."
        ),
        "title": _str_prop("Conversation title when grouped by conversation, else empty string."),
        "model": _str_prop("Canonical model identifier, 'mixed', or 'none'."),
        "conversation_count": _nonneg_int("Number of conversations included in this bucket."),
        "turn_count": _nonneg_int("Number of LLM generation turns included in this bucket."),
        "input_tokens": _nonneg_int("Total uncached prompt input tokens."),
        "cached_input_tokens": _nonneg_int("Total cache-read prompt input tokens."),
        "output_tokens": _nonneg_int("Total output tokens (including thinking tokens)."),
        "thinking_tokens": _nonneg_int("Total reasoning/thinking tokens reported."),
        "total_tokens": _nonneg_int("Sum of input_tokens, cached_input_tokens, and output_tokens."),
        "cost_usd": _nonneg_num("Estimated total USD cost rounded to 6 decimal places."),
    }


def _report_bucket_properties() -> dict[str, object]:
    """Return JSON Schema property definitions for `token-report` buckets including UUIDs."""
    props = _ledger_row_properties()
    ordered: dict[str, object] = {}
    for key, val in props.items():
        ordered[key] = val
        if key == "conversation_id":
            ordered["conversation_ids"] = {
                "type": "array",
                "description": "Sorted distinct conversation UUIDs included in this bucket.",
                "items": {"type": "string", "description": "Antigravity conversation UUID."},
            }
    return ordered


def build_ledger_row_json_schema() -> dict[str, object]:
    """Build the JSON Schema Draft 2020-12 contract for single `jsonl` VisiData stream lines."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://schemas.wallace.local/v1/ledger-row.schema.json",
        "title": "Wallace Ledger Row (NDJSON / JSONL)",
        "description": (
            "Single newline-delimited JSON (JSONL) ledger record emitted by "
            "'wallace report ... --format jsonl' for VisiData and streaming pipelines."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": list(CSV_COLUMN_ORDER),
        "properties": _ledger_row_properties(),
    }


def build_report_json_schema() -> dict[str, object]:
    """Build the JSON Schema Draft 2020-12 contract for `wallace report --format json`."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://schemas.wallace.local/v1/token-report.schema.json",
        "title": "Wallace Token & Cost Audit Report",
        "description": (
            "Aggregated token usage and USD cost report across Antigravity IDE and CLI "
            "brain directories, grouped by timeframe, project, feature, or conversation."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": ["group_by", "period", "interval", "totals", "buckets"],
        "properties": {
            "group_by": _str_prop(
                "Entity grouping dimension applied to the buckets array.",
                enum=["none", "summary", "project", "feature", "conversation", "model", "source"],
            ),
            "period": _str_prop(
                "Timeframe bucketing mode applied to turns.",
                enum=["none", "day", "week", "month", "interval"],
            ),
            "interval": _str_prop(
                "Custom duration specification when period is 'interval', else empty."
            ),
            "totals": {
                "$ref": "#/$defs/bucket",
                "description": "Grand total token counts and USD cost across all buckets.",
            },
            "buckets": {
                "type": "array",
                "description": "Ordered list of aggregated token usage buckets.",
                "items": {"$ref": "#/$defs/bucket"},
            },
        },
        "$defs": {
            "bucket": {
                "type": "object",
                "description": "Aggregated token usage and USD cost bucket.",
                "additionalProperties": False,
                "required": list(BUCKET_REQUIRED_FIELDS),
                "properties": _report_bucket_properties(),
            }
        },
    }


def _usage_totals_subschema(*, include_subagent_count: bool = False) -> dict[str, object]:
    """Build reusable JSON Schema sub-definition for `self_usage` / `total_usage` blocks."""
    props: dict[str, object] = {
        "turn_count": _nonneg_int("Turn count."),
        "input_tokens": _nonneg_int("Uncached input tokens."),
        "cached_input_tokens": _nonneg_int("Cache-read input tokens."),
        "output_tokens": _nonneg_int("Output tokens."),
        "thinking_tokens": _nonneg_int("Thinking tokens."),
        "total_tokens": _nonneg_int("Total tokens."),
        "cost_usd": _nonneg_num("Estimated USD cost."),
    }
    if include_subagent_count:
        props["subagent_count"] = _nonneg_int("Number of descendant subagent conversations.")
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(props.keys()),
        "properties": props,
    }


def _strict_array_of(description: str, item_props: dict[str, object]) -> dict[str, object]:
    """Build a JSON Schema array of strict objects defined by `item_props`."""
    return {
        "type": "array",
        "description": description,
        "items": {
            "type": "object",
            "additionalProperties": False,
            "required": list(item_props.keys()),
            "properties": item_props,
        },
    }


def _model_breakdown_item_props() -> dict[str, object]:
    """Return property descriptors for per-model token and cost breakdown items."""
    return {
        "model": _str_prop("Model identifier."),
        **_usage_totals_subschema()["properties"],  # type: ignore[dict-item]
    }


def _conversation_nested_arrays() -> dict[str, object]:
    """Build `models`, `subagents`, and `turns` array schemas for conversation queries."""
    sub_props: dict[str, object] = {
        "conversation_id": _str_prop("Subagent UUID."),
        "agent_name": _str_prop("Subagent role/preset."),
        "feature": _str_prop("Resolved subagent feature."),
        "title": _str_prop("Subagent title."),
        "primary_model": _str_prop("Dominant model."),
        "total_tokens": _nonneg_int("Total tokens."),
        "cost_usd": _nonneg_num("Estimated USD cost."),
    }
    turn_props: dict[str, object] = {
        "turn_index": _nonneg_int("1-based turn index.", minimum=1),
        "created_at": _str_prop("Turn ISO-8601 timestamp."),
        "model": _str_prop("Turn model identifier."),
        "input_tokens": _nonneg_int("Turn uncached input tokens."),
        "cached_input_tokens": _nonneg_int("Turn cached input tokens."),
        "output_tokens": _nonneg_int("Turn output tokens."),
        "thinking_tokens": _nonneg_int("Turn thinking tokens."),
        "total_tokens": _nonneg_int("Turn total tokens."),
        "cost_usd": _nonneg_num("Turn estimated USD cost."),
    }
    return {
        "models": _strict_array_of(
            "Per-model token and cost breakdown across self and subagents.",
            _model_breakdown_item_props(),
        ),
        "subagents": _strict_array_of("Summary of descendant subagent conversations.", sub_props),
        "turns": _strict_array_of(
            "Optional chronological turn-by-turn ledger when --turns is set.", turn_props
        ),
    }


def build_conversation_usage_json_schema() -> dict[str, object]:
    """Build the JSON Schema Draft 2020-12 contract for `wallace query <conversation_id>`."""
    root_props: dict[str, object] = {
        "conversation_id": _str_prop("Conversation UUID."),
        "source": _str_prop("Origin environment.", enum=["ide", "cli", "standalone"]),
        "project": _str_prop("Resolved project name."),
        "feature": _str_prop("Resolved feature or Work Package ID."),
        "title": _str_prop("Conversation title."),
        "git_branch": _str_prop("Git branch if recorded."),
        "parent_conversation_id": _str_prop("Immediate parent conversation UUID if subagent."),
        "root_conversation_id": _str_prop("Root conversation UUID in subagent hierarchy."),
        "primary_model": _str_prop("Dominant model identifier."),
        "started_at": _str_prop("Earliest ISO-8601 timestamp."),
        "last_timestamp": _str_prop("Latest ISO-8601 timestamp."),
        "self_usage": _usage_totals_subschema(),
        "subagent_usage": _usage_totals_subschema(include_subagent_count=True),
        "total_usage": _usage_totals_subschema(),
        **_conversation_nested_arrays(),
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://schemas.wallace.local/v1/conversation-usage.schema.json",
        "title": "Wallace Single-Conversation Token & Cost Audit",
        "description": (
            "Detailed self, subagent, and combined token usage and USD cost breakdown "
            "for a single Antigravity conversation ID."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": [k for k in root_props if k != "turns"],
        "properties": root_props,
    }


def build_task_usage_json_schema() -> dict[str, object]:
    """Build the JSON Schema Draft 2020-12 contract for `wallace task <TASK-ID> --format json`."""
    conv_props: dict[str, object] = {
        "conversation_id": _str_prop("Contributing conversation UUID."),
        "source": _str_prop("Origin environment.", enum=["ide", "cli", "standalone"]),
        "project": _str_prop("Resolved project slug."),
        "feature": _str_prop("Resolved conversation feature or task identifier."),
        "title": _str_prop("Conversation display title."),
        "agent_name": _str_prop("Subagent preset or worker roster name."),
        "role": _str_prop("Attributed worker role.", enum=["implementation", "qa"]),
        "attribution_share": _nonneg_num(
            "Fraction (0.0 to 1.0) of the conversation attributed to this task.", maximum=1.0
        ),
        **_usage_totals_subschema()["properties"],  # type: ignore[dict-item]
    }
    root_props: dict[str, object] = {
        "task_id": _str_prop("Canonical uppercase Work Package or task identifier."),
        "project": _str_prop("Resolved or requested project slug."),
        "include_qa": _bool_prop("Whether QA conversations were included in totals."),
        "conversation_count": _nonneg_int("Number of distinct conversations attributed."),
        "conversation_ids": {
            "type": "array",
            "description": "Sorted distinct conversation UUIDs contributing to this task.",
            "items": {"type": "string", "description": "Antigravity conversation UUID."},
        },
        **_usage_totals_subschema()["properties"],  # type: ignore[dict-item]
        "models": _strict_array_of(
            "Per-model token and USD cost breakdown across attributed conversations.",
            _model_breakdown_item_props(),
        ),
        "conversations": _strict_array_of(
            "Per-conversation breakdown distinguishing implementation and QA roles.",
            conv_props,
        ),
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://schemas.wallace.local/v1/task-usage.schema.json",
        "title": "Wallace Task Token & Cost Spend Summary",
        "description": (
            "Aggregated token usage, turn count, USD cost, per-model breakdown, and "
            "contributing conversations for a single Work Package or task identifier."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": list(root_props.keys()),
        "properties": root_props,
    }


def _bool_prop(description: str) -> dict[str, object]:
    """Build a boolean JSON Schema property descriptor."""
    return {"type": "boolean", "description": description}


def build_report_csvw_schema() -> dict[str, object]:
    """Build the W3C CSV on the Web (CSVW) metadata descriptor for CSV exports."""
    specs = [
        ("period", "Period", "string", True),
        ("period_start", "Period Start", "string", False),
        ("source", "Source", "string", True),
        ("project", "Project", "string", True),
        ("feature", "Feature", "string", True),
        ("conversation_id", "Conversation ID", "string", False),
        ("title", "Title", "string", False),
        ("model", "Model", "string", True),
        ("conversation_count", "Conversations", "integer", True),
        ("turn_count", "Turns", "integer", True),
        ("input_tokens", "Input Tokens", "integer", True),
        ("cached_input_tokens", "Cached Input Tokens", "integer", True),
        ("output_tokens", "Output Tokens", "integer", True),
        ("thinking_tokens", "Thinking Tokens", "integer", True),
        ("total_tokens", "Total Tokens", "integer", True),
        ("cost_usd", "Cost USD", "decimal", True),
    ]
    columns = [
        {"name": name, "titles": title, "datatype": dtype, "required": req}
        for name, title, dtype, req in specs
    ]
    return {
        "@context": "http://www.w3.org/ns/csvw",
        "url": "token-report.csv",
        "dc:title": "Wallace Token & Cost CSV Report",
        "dc:description": (
            "RFC 4180 CSV export of aggregated token usage and USD cost with "
            "spreadsheet formula-injection sanitization on string cells."
        ),
        "dialect": {
            "delimiter": ",",
            "quoteChar": '"',
            "doubleQuote": True,
            "lineTerminators": ["\n", "\r\n"],
            "encoding": "utf-8",
            "header": True,
        },
        "tableSchema": {"columns": columns},
    }


def render_schema_document(name: str, fmt: str = "json-schema") -> str:
    """Render a named Wallace schema artifact as deterministic, newline-terminated JSON."""
    if name not in SCHEMA_NAMES:
        available = ", ".join(SCHEMA_NAMES)
        raise KeyError(f"Unknown schema '{name}'. Available schemas: {available}.")

    if fmt in ("csvw", "table-schema"):
        if name != "token-report":
            raise KeyError(
                f"Schema '{name}' only supports 'json-schema' (CSVW is defined for 'token-report')."
            )
        doc = build_report_csvw_schema()
    elif fmt == "json-schema":
        builders = {
            "token-report": build_report_json_schema,
            "ledger-row": build_ledger_row_json_schema,
            "conversation-usage": build_conversation_usage_json_schema,
            "task-usage": build_task_usage_json_schema,
        }
        doc = builders[name]()
    else:
        raise KeyError(f"Unsupported schema format '{fmt}'. Choose 'json-schema' or 'csvw'.")
    return json.dumps(doc, indent=2) + "\n"
