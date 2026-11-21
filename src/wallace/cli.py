"""CLI command execution handlers and main entrypoint for `wallace`."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

from wallace.aggregator import aggregate_report, filter_conversations
from wallace.browser import launch_browser
from wallace.cli_parser import (
    EXIT_ERROR,
    EXIT_OK,
    EXIT_USAGE,
    build_parser,
    render_shell_completions,
)
from wallace.config import AppConfig, load_config, render_config_toml
from wallace.exporters import (
    render_conversation_query_json,
    render_csv,
    render_json,
    render_jsonl,
    render_plain,
    render_table,
    render_task_usage_json,
    render_tsv,
    should_use_color,
)
from wallace.installer import install_launcher
from wallace.message_loader import (
    build_conversation_messages_payload,
    load_conversation_messages,
    render_conversation_messages_json,
    render_conversation_messages_text,
    resolve_conversation_record,
)
from wallace.metrics import record_browser_view, render_prometheus_text, serve_metrics_http
from wallace.models import ConversationRecord, ScanReport
from wallace.query import query_conversation_usage
from wallace.scanner import scan_brains
from wallace.schemas import SCHEMA_NAMES, render_schema_document
from wallace.task_query import query_task_usage, render_task_usage_table
from wallace.timeframes import resolve_filter_bounds, resolve_timeframe_spec
from wallace.visidata_integration import (
    export_sqlite_workbook,
    install_visidata_plugin,
    launch_visidata_workbook,
    render_visidata_plugin,
)


def _write_output(content: str, output_path: Path | None) -> None:
    """Write `content` either to `output_path` or directly to `sys.stdout`."""
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        return
    sys.stdout.write(content)


def _write_err(message: str) -> None:
    """Write a newline-terminated diagnostic message to `sys.stderr`."""
    sys.stderr.write(f"{message}\n")


def _apply_cli_dir_overrides(ns: argparse.Namespace, cfg: AppConfig) -> AppConfig:
    """Return an `AppConfig` incorporating provider directory override flags."""
    ide_raw: Path | None = getattr(ns, "ide_dir", None)
    cli_raw: Path | None = getattr(ns, "cli_dir", None)
    claude_raw: Path | None = getattr(ns, "claude_dir", None)
    grok_raw: Path | None = getattr(ns, "grok_dir", None)
    codex_raw: Path | None = getattr(ns, "codex_dir", None)
    brain_raw: list[Path] = list(getattr(ns, "brain_dir", []) or [])
    return replace(
        cfg,
        ide_dir=ide_raw.expanduser() if ide_raw is not None else cfg.ide_dir,
        cli_dir=cli_raw.expanduser() if cli_raw is not None else cfg.cli_dir,
        claude_dir=claude_raw.expanduser() if claude_raw is not None else cfg.claude_dir,
        grok_dir=grok_raw.expanduser() if grok_raw is not None else cfg.grok_dir,
        codex_dir=codex_raw.expanduser() if codex_raw is not None else cfg.codex_dir,
        extra_brain_dirs=tuple(p.expanduser() for p in brain_raw)
        if brain_raw
        else cfg.extra_brain_dirs,
    )


def _validate_ns_timeframe(ns: argparse.Namespace) -> bool:
    """Validate `--timeframe`, `--since`, and `--until` early; write error if invalid."""
    try:
        resolve_filter_bounds(
            timeframe=str(getattr(ns, "timeframe", "")),
            since=str(getattr(ns, "since", "")),
            until=str(getattr(ns, "until", "")),
        )
    except ValueError as exc:
        _write_err(f"Error: {exc}")
        return False
    return True


def _scan_filtered(
    ns: argparse.Namespace,
    cfg: AppConfig,
    *,
    source_override: str | None = None,
    apply_tf: bool = True,
) -> list[ConversationRecord]:
    """Scan brains with CLI directory overrides and apply namespace filters."""
    effective_cfg = _apply_cli_dir_overrides(ns, cfg)
    return filter_conversations(
        scan_brains(effective_cfg),
        source=source_override
        if source_override is not None
        else str(getattr(ns, "source", "all")),
        project=str(getattr(ns, "project", "")),
        feature=str(getattr(ns, "feature", "")),
        timeframe=str(getattr(ns, "timeframe", "")) if apply_tf else "",
        since=str(getattr(ns, "since", "")),
        until=str(getattr(ns, "until", "")),
    )


def _handle_report(ns: argparse.Namespace, cfg: AppConfig) -> int:
    """Execute `wallace report <verb>` and emit the requested format or SQLite workbook."""
    if not _validate_ns_timeframe(ns):
        return EXIT_USAGE
    filtered = _scan_filtered(ns, cfg)

    fmt = str(ns.format)
    if fmt == "sqlite":
        if ns.output is None:
            _write_err(
                "Error: '--format sqlite' requires '--output <file.sqlite>' because SQLite "
                "databases are binary files."
            )
            return EXIT_USAGE
        export_sqlite_workbook(
            filtered, ns.output, period=str(ns.period), interval_spec=str(ns.interval)
        )
        return EXIT_OK

    try:
        report = aggregate_report(
            filtered,
            group_by=str(ns.group_by),
            period=str(ns.period),
            interval_spec=str(ns.interval),
            include_subagents=bool(ns.include_subagents),
        )
    except ValueError as exc:
        _write_err(f"Error: {exc}")
        return EXIT_USAGE

    rendered = _format_report_output(report, fmt=fmt, has_output_file=(ns.output is not None))
    _write_output(rendered, ns.output)
    return EXIT_OK


def _format_report_output(report: ScanReport, *, fmt: str, has_output_file: bool) -> str:
    """Dispatch `ScanReport` rendering to the requested text/structured serializer."""
    serializers = {
        "json": render_json,
        "jsonl": render_jsonl,
        "tsv": render_tsv,
        "csv": render_csv,
        "plain": render_plain,
    }
    if fmt in serializers:
        return serializers[fmt](report)
    return render_table(report, color=((not has_output_file) and should_use_color(sys.stdout)))


def _handle_browse(ns: argparse.Namespace, cfg: AppConfig) -> int:
    """Execute `wallace browse` interactive single-viewport TUI conversation browser."""
    if not _validate_ns_timeframe(ns):
        return EXIT_USAGE
    raw_tf = str(getattr(ns, "timeframe", ""))
    init_tf = resolve_timeframe_spec(raw_tf).label if raw_tf.strip() else "all"
    effective_cfg = _apply_cli_dir_overrides(ns, cfg)
    raw_src = str(getattr(ns, "source", "all"))
    pre_src = raw_src if raw_src in ("ide", "cli", "standalone") else "all"
    init_tab = "agy" if pre_src != "all" else raw_src
    filtered = _scan_filtered(ns, cfg, source_override=pre_src, apply_tf=False)
    return launch_browser(
        filtered,
        effective_cfg,
        initial_source=init_tab,
        initial_query=str(getattr(ns, "query", "")),
        initial_timeframe=init_tf,
        conversation_id=str(getattr(ns, "conversation_id", "")),
    )


def _handle_conversation_read(ns: argparse.Namespace, cfg: AppConfig) -> int:
    """Execute `wallace conversation read <id> [--format text|json]`."""
    effective_cfg = _apply_cli_dir_overrides(ns, cfg)
    records = scan_brains(effective_cfg)
    try:
        rec = resolve_conversation_record(records, str(ns.conversation_id))
    except LookupError as exc:
        _write_err(f"Error: {exc}")
        return EXIT_ERROR
    messages = load_conversation_messages(rec, effective_cfg)
    record_browser_view(source=rec.source, view="read")
    if str(ns.format) == "json":
        payload = build_conversation_messages_payload(rec, messages)
        rendered = render_conversation_messages_json(payload)
    else:
        use_color = (ns.output is None) and should_use_color(sys.stdout)
        rendered = render_conversation_messages_text(rec, messages, color=use_color)
    _write_output(rendered, ns.output)
    return EXIT_OK


def _handle_conversation_query(ns: argparse.Namespace, cfg: AppConfig) -> int:
    """Execute `wallace query <id>` / `wallace conversation show|read|list`."""
    if ns.noun == "conversation":
        verb = getattr(ns, "verb", None)
        if verb == "read":
            return _handle_conversation_read(ns, cfg)
        if verb == "list":
            return _handle_report(ns, cfg)
        if verb != "show":
            _write_err("Error: Specify 'wallace conversation show|read|list <CONVERSATION_ID>'.")
            return EXIT_USAGE

    effective_cfg = _apply_cli_dir_overrides(ns, cfg)
    records = scan_brains(effective_cfg)
    try:
        payload = query_conversation_usage(
            records, str(ns.conversation_id), include_turns=bool(ns.turns)
        )
    except LookupError as exc:
        _write_err(f"Error: {exc}")
        return EXIT_ERROR

    _write_output(render_conversation_query_json(payload), ns.output)
    return EXIT_OK


def _handle_task(ns: argparse.Namespace, cfg: AppConfig) -> int:
    """Execute `wallace task <TASK-ID>` and emit schema-validated JSON or aligned table."""
    if not _validate_ns_timeframe(ns):
        return EXIT_USAGE
    records = filter_conversations(
        scan_brains(_apply_cli_dir_overrides(ns, cfg)),
        timeframe=str(getattr(ns, "timeframe", "")),
        since=str(getattr(ns, "since", "")),
        until=str(getattr(ns, "until", "")),
    )
    extra_convs = [str(item) for item in (getattr(ns, "conversation", []) or [])]
    try:
        payload = query_task_usage(
            records,
            str(ns.task_id),
            project=str(ns.project),
            extra_conversations=extra_convs,
            include_qa=bool(ns.include_qa),
        )
    except LookupError as exc:
        _write_err(f"Error: {exc}")
        return EXIT_ERROR

    if str(ns.format) == "json":
        rendered = render_task_usage_json(payload)
    else:
        rendered = render_task_usage_table(
            payload, color=((ns.output is None) and should_use_color(sys.stdout))
        )
    _write_output(rendered, ns.output)
    return EXIT_OK


def _handle_visidata(ns: argparse.Namespace, cfg: AppConfig) -> int:
    """Execute `wallace visidata open|config|install`."""
    verb = getattr(ns, "verb", None) or "open"
    if verb == "config":
        _write_output(render_visidata_plugin(), getattr(ns, "output", None))
        return EXIT_OK
    if verb == "install":
        plugin_path, rc_path = install_visidata_plugin(getattr(ns, "output", None))
        _write_err(f"Installed Wallace VisiData plugin to {plugin_path} (loaded via {rc_path})")
        return EXIT_OK

    if not _validate_ns_timeframe(ns):
        return EXIT_USAGE
    return launch_visidata_workbook(
        _scan_filtered(ns, cfg),
        period=str(getattr(ns, "period", "day")),
        interval_spec=str(getattr(ns, "interval", "7d")),
    )


def _handle_config(ns: argparse.Namespace, cfg: AppConfig) -> int:
    """Execute `wallace config show|init`."""
    toml_text = render_config_toml(cfg)
    if ns.verb in (None, "show") or ns.output is None:
        sys.stdout.write(toml_text)
        return EXIT_OK

    resolved = ns.output.expanduser()
    if resolved.exists() and not ns.force:
        _write_err(
            f"Error: Configuration file '{resolved}' already exists. Pass '--force' to overwrite."
        )
        return EXIT_ERROR
    _write_output(toml_text, resolved)
    _write_err(f"Wrote default configuration to {resolved}")
    return EXIT_OK


def _handle_metrics(ns: argparse.Namespace, cfg: AppConfig) -> int:
    """Execute `wallace metrics export|serve`."""
    if ns.verb in (None, "export"):
        _write_output(render_prometheus_text(cfg), getattr(ns, "output", None))
        return EXIT_OK

    host = str(ns.host) if ns.host else cfg.metrics_host
    port = int(ns.port) if ns.port is not None else cfg.metrics_port
    serve_metrics_http(
        replace(cfg, metrics_host=host, metrics_port=port),
        refresh_seconds=float(ns.refresh_seconds),
    )
    return EXIT_OK


def _handle_schema(ns: argparse.Namespace) -> int:
    """Execute `wallace schema [--list | <name>]`."""
    available = ", ".join(SCHEMA_NAMES)
    if ns.list_schemas:
        sys.stdout.write("\n".join(SCHEMA_NAMES) + "\n")
        return EXIT_OK
    if not ns.name:
        _write_err(
            f"Error: Missing schema name. Available schemas: {available}.\n"
            "Run 'wallace schema --list' or 'wallace schema token-report'."
        )
        return EXIT_USAGE
    try:
        content = render_schema_document(str(ns.name), fmt=str(ns.format))
    except KeyError as exc:
        _write_err(f"Error: {exc.args[0]}")
        return EXIT_ERROR
    _write_output(content, ns.output)
    return EXIT_OK


def _handle_install(ns: argparse.Namespace) -> int:
    """Execute `wallace install [--bin-dir <DIR>]`."""
    try:
        shim_path = install_launcher(getattr(ns, "bin_dir", None))
    except OSError as exc:
        _write_err(f"Error: Failed to install wallace launcher: {exc}")
        return EXIT_ERROR
    _write_err(f"Installed wallace launcher to {shim_path}")
    return EXIT_OK


def _normalize_default_args(args: list[str]) -> list[str]:
    """Insert default `['report', 'summary']` when bare flags or verb-less `report` are passed."""
    top_flags = ("-h", "--help", "--version", "--completions")
    if args and args[0] == "report" and len(args) > 1 and args[1].startswith("-"):
        if args[1] not in ("-h", "--help"):
            return ["report", "summary", *args[1:]]
        return args
    is_bare_or_flag = not args or (args[0].startswith("-") and args[0] not in top_flags)
    if is_bare_or_flag and "--config" not in args:
        return ["report", "summary", *args]
    return args


def _ensure_report_defaults(ns: argparse.Namespace) -> None:
    """Populate default report attributes when `wallace report` is called without a verb."""
    if getattr(ns, "verb", None) is not None:
        return
    ns.verb = "summary"
    for attr in ("ide_dir", "cli_dir", "claude_dir", "grok_dir", "codex_dir", "output"):
        if not hasattr(ns, attr):
            setattr(ns, attr, None)
    for attr in ("project", "feature", "timeframe", "since", "until"):
        if not hasattr(ns, attr):
            setattr(ns, attr, "")
    other: dict[str, object] = {
        "brain_dir": [],
        "source": "all",
        "period": "none",
        "interval": "7d",
        "group_by": "summary",
        "include_subagents": False,
        "format": "table",
    }
    for attr, val in other.items():
        if not hasattr(ns, attr):
            setattr(ns, attr, val)


def _dispatch_command(ns: argparse.Namespace, cfg: AppConfig) -> int:
    """Dispatch parsed CLI namespace to the matching noun handler."""
    if ns.noun in (None, "report"):
        _ensure_report_defaults(ns)
        return _handle_report(ns, cfg)
    cfg_handlers = {
        "browse": _handle_browse,
        "conversation": _handle_conversation_query,
        "query": _handle_conversation_query,
        "task": _handle_task,
        "visidata": _handle_visidata,
        "config": _handle_config,
        "metrics": _handle_metrics,
    }
    if ns.noun in cfg_handlers:
        return cfg_handlers[ns.noun](ns, cfg)
    if ns.noun == "schema":
        return _handle_schema(ns)
    if ns.noun == "install":
        return _handle_install(ns)
    return EXIT_USAGE


def _handle_help_all(raw_args: list[str]) -> int:
    """Render extended `--help-all` output and return `EXIT_OK`."""
    full_parser = build_parser(advanced_visible=True)
    filtered = [a for a in raw_args if a != "--help-all"]
    if not filtered:
        full_parser.print_help(sys.stdout)
        return EXIT_OK
    full_parser.parse_args([*filtered, "--help"])
    return EXIT_OK


def main(argv: Sequence[str] | None = None) -> int:
    """Run the `wallace` CLI and return a documented Unix exit status code."""
    raw_args = list(sys.argv[1:] if argv is None else argv)
    if "--help-all" in raw_args:
        return _handle_help_all(raw_args)

    args = _normalize_default_args(raw_args)
    is_help = any(f in args for f in ("-h", "--help"))
    exec_parser = build_parser(advanced_visible=(not is_help))
    try:
        ns = exec_parser.parse_args(args)
    except SystemExit as exc:
        return int(exc.code) if isinstance(exc.code, int) else EXIT_OK

    if ns.completions:
        sys.stdout.write(render_shell_completions(str(ns.completions)))
        return EXIT_OK

    cfg = load_config(config_path=ns.config)
    return _dispatch_command(ns, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
