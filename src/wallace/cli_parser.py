"""Noun-verb CLI parser construction, progressive flag disclosure, and completions."""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path
from typing import NoReturn

from wallace import __version__

# region Constants & Defaults

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2

KNOWN_FLAGS: tuple[str, ...] = (
    "--help",
    "--help-all",
    "--version",
    "--completions",
    "--config",
    "--ide-dir",
    "--cli-dir",
    "--brain-dir",
    "--source",
    "--project",
    "--feature",
    "--period",
    "--interval",
    "--group-by",
    "--since",
    "--until",
    "--format",
    "--output",
    "--include-subagents",
    "--turns",
    "--list",
    "--host",
    "--port",
    "--refresh-seconds",
    "--force",
)

REPORT_VERB_SPECS: dict[str, tuple[str, str]] = {
    "summary": ("summary", "none"),
    "projects": ("project", "none"),
    "features": ("feature", "none"),
    "conversations": ("conversation", "none"),
    "models": ("model", "none"),
    "sources": ("source", "none"),
    "daily": ("feature", "day"),
    "weekly": ("feature", "week"),
    "monthly": ("feature", "month"),
    "interval": ("feature", "interval"),
}

# endregion


# region Argument Parsing


class ActionableArgumentParser(argparse.ArgumentParser):
    """`ArgumentParser` subclass emitting actionable flag suggestions to `stderr`."""

    def error(self, message: str) -> NoReturn:
        """Print an actionable error message with closest flag match and exit `2`."""
        hint = _suggest_unknown_flag(message)
        full_msg = f"Error: {message}. {hint}" if hint else f"Error: {message}"
        print(f"{full_msg}\nRun '{self.prog} --help' for usage details.", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def _suggest_unknown_flag(message: str) -> str:
    """Return a `'Did you mean ...?'` hint when `message` mentions an unknown flag."""
    if "unrecognized arguments:" not in message:
        return ""
    bad_tokens = message.split("unrecognized arguments:", 1)[1].strip().split()
    for token in bad_tokens:
        flag = token.split("=", 1)[0]
        if flag.startswith("-"):
            matches = difflib.get_close_matches(flag, KNOWN_FLAGS, n=1, cutoff=0.6)
            if matches:
                return f"Did you mean '{matches[0]}'?"
    return ""


def _add_common_filter_flags(parser: argparse.ArgumentParser, *, advanced_visible: bool) -> None:
    """Attach source, project, feature, date, and directory override flags."""
    adv_help = None if advanced_visible else argparse.SUPPRESS
    parser.add_argument(
        "--source",
        choices=("all", "ide", "cli", "standalone"),
        default="all",
        help="Filter by Antigravity source ('all', 'ide', 'cli', or 'standalone').",
    )
    parser.add_argument("--project", default="", help="Substring filter on project name.")
    parser.add_argument("--feature", default="", help="Substring filter on feature or WP ID.")
    parser.add_argument(
        "--since",
        default="",
        help=adv_help or "Include turns/conversations at or after ISO-8601 timestamp.",
    )
    parser.add_argument(
        "--until",
        default="",
        help=adv_help or "Include turns/conversations at or before ISO-8601 timestamp.",
    )
    parser.add_argument("--ide-dir", type=Path, default=None, help=adv_help or "IDE root override.")
    parser.add_argument("--cli-dir", type=Path, default=None, help=adv_help or "CLI root override.")
    parser.add_argument(
        "--brain-dir",
        action="append",
        type=Path,
        default=[],
        help=adv_help or "Additional standalone brain directory (repeatable).",
    )


def _add_report_flags(
    parser: argparse.ArgumentParser,
    *,
    default_group: str,
    default_period: str,
    advanced_visible: bool,
) -> None:
    """Attach timeframe, grouping, and VisiData-ready output format flags to a report verb."""
    _add_common_filter_flags(parser, advanced_visible=advanced_visible)
    adv_help = None if advanced_visible else argparse.SUPPRESS
    parser.add_argument(
        "--period",
        choices=("none", "day", "week", "month", "interval"),
        default=default_period,
        help="Bucket spend by timeframe ('none', 'day', 'week', 'month', or 'interval').",
    )
    parser.add_argument(
        "--interval",
        default="7d",
        help="Duration for '--period interval' (e.g. '1h', '6h', '7d', '14d', '30d').",
    )
    parser.add_argument(
        "--group-by",
        choices=("none", "summary", "project", "feature", "conversation", "model", "source"),
        default=default_group,
        help=adv_help or "Entity dimension combined with '--period'.",
    )
    parser.add_argument(
        "--format",
        choices=("table", "json", "jsonl", "tsv", "csv", "plain", "sqlite"),
        default="table",
        help="Output format ('table', 'json', 'jsonl', 'tsv', 'csv', 'plain', or 'sqlite').",
    )
    parser.add_argument("--output", type=Path, default=None, help="Write output to file path.")
    parser.add_argument(
        "--include-subagents",
        action="store_true",
        help=adv_help or "List spawned subagents individually in conversation view.",
    )


def _attach_query_args(parser: argparse.ArgumentParser, *, advanced_visible: bool) -> None:
    """Attach arguments to `conversation show` / `query`."""
    adv_help = None if advanced_visible else argparse.SUPPRESS
    parser.add_argument("conversation_id", help="Exact conversation UUID or unambiguous prefix.")
    parser.add_argument(
        "--turns",
        action="store_true",
        help="Include chronological turn-by-turn token and cost array in JSON output.",
    )
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output file.")
    parser.add_argument("--ide-dir", type=Path, default=None, help=adv_help or "IDE root override.")
    parser.add_argument("--cli-dir", type=Path, default=None, help=adv_help or "CLI root override.")
    parser.add_argument(
        "--brain-dir",
        action="append",
        type=Path,
        default=[],
        help=adv_help or "Additional standalone brain directory.",
    )


def _register_conversation_and_visidata(
    subparsers: argparse._SubParsersAction[ActionableArgumentParser],
    *,
    advanced_visible: bool,
) -> None:
    """Register `conversation`, `query`, and `visidata` subcommands."""
    conv_p = subparsers.add_parser("conversation", help="Inspect a single conversation ledger.")
    conv_sub = conv_p.add_subparsers(dest="verb")
    show_p = conv_sub.add_parser("show", help="Return token and USD cost JSON for a conversation.")
    _attach_query_args(show_p, advanced_visible=advanced_visible)

    query_p = subparsers.add_parser(
        "query", help="Query a conversation ID (or prefix) and return token/cost JSON."
    )
    _attach_query_args(query_p, advanced_visible=advanced_visible)

    vd_p = subparsers.add_parser("visidata", help="VisiData (vd) exploration & plugin integration.")
    vd_sub = vd_p.add_subparsers(dest="verb")
    open_p = vd_sub.add_parser("open", help="Open multi-sheet Wallace ledger directly in VisiData.")
    _add_common_filter_flags(open_p, advanced_visible=advanced_visible)
    open_p.add_argument(
        "--period",
        choices=("day", "week", "month", "interval"),
        default="day",
        help="Timeframe granularity for the daily_feature_spend sheet.",
    )
    open_p.add_argument("--interval", default="7d", help="Duration when '--period interval'.")

    cfg_p = vd_sub.add_parser("config", help="Print Wallace VisiData plugin source to stdout.")
    cfg_p.add_argument("--output", type=Path, default=None, help="Optional plugin output path.")

    inst_p = vd_sub.add_parser(
        "install", help="Install Wallace VisiData plugin and .visidatarc hook."
    )
    inst_p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional target directory override (default: ~/.visidata + ~/.visidatarc).",
    )


def _register_admin_subparsers(
    subparsers: argparse._SubParsersAction[ActionableArgumentParser],
) -> None:
    """Register `config`, `metrics`, and `schema` subcommands on `subparsers`."""
    cfg_p = subparsers.add_parser("config", help="Inspect or initialize TOML configuration.")
    cfg_sub = cfg_p.add_subparsers(dest="verb")
    cfg_sub.add_parser("show", help="Print active TOML configuration to stdout.")
    init_p = cfg_sub.add_parser("init", help="Write editable default TOML configuration.")
    init_p.add_argument("--output", type=Path, default=None, help="Destination TOML path.")
    init_p.add_argument("--force", action="store_true", help="Overwrite existing config file.")

    met_p = subparsers.add_parser("metrics", help="Export or serve Prometheus telemetry.")
    met_sub = met_p.add_subparsers(dest="verb")
    exp_p = met_sub.add_parser("export", help="Write Prometheus exposition text to stdout/file.")
    exp_p.add_argument("--output", type=Path, default=None, help="Optional `.prom` output path.")
    srv_p = met_sub.add_parser("serve", help="Run HTTP Prometheus exporter daemon.")
    srv_p.add_argument("--host", default=None, help="Bind address override.")
    srv_p.add_argument("--port", type=int, default=None, help="TCP port override.")
    srv_p.add_argument("--refresh-seconds", type=float, default=30.0, help="Scan refresh interval.")

    sch_p = subparsers.add_parser("schema", help="Emit JSON Schema and W3C CSVW contracts.")
    sch_p.add_argument("name", nargs="?", default="", help="Schema artifact name.")
    sch_p.add_argument("--list", action="store_true", dest="list_schemas", help="List schemas.")
    sch_p.add_argument(
        "--format",
        choices=("json-schema", "csvw", "table-schema"),
        default="json-schema",
        help="Schema standard format.",
    )
    sch_p.add_argument("--output", type=Path, default=None, help="Optional schema output file.")


def build_parser(*, advanced_visible: bool = False) -> argparse.ArgumentParser:
    """Construct the noun-verb CLI parser for `wallace`."""
    parser = ActionableArgumentParser(
        prog="wallace",
        description=(
            "Oscar Wallace: Forensic token usage and USD cost auditor for Antigravity IDE and CLI "
            "brain directories, with timeframe rollups and VisiData integration."
        ),
    )
    parser.add_argument("--version", action="version", version=f"wallace {__version__}")
    parser.add_argument(
        "--help-all",
        action="store_true",
        help="Show extended power-user flags (date bounds, directory overrides, completions).",
    )
    parser.add_argument(
        "--completions",
        choices=("bash", "zsh", "fish"),
        default=None,
        help=None if advanced_visible else argparse.SUPPRESS,
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to TOML configuration file (default: ~/.config/wallace/config.toml).",
    )

    subparsers = parser.add_subparsers(dest="noun")
    report_p = subparsers.add_parser(
        "report", help="Aggregate token usage and USD spend by timeframe, project, or feature."
    )
    report_sub = report_p.add_subparsers(dest="verb")
    for verb, (def_grp, def_per) in REPORT_VERB_SPECS.items():
        vp = report_sub.add_parser(verb, help=f"Report spend ({verb}).")
        _add_report_flags(
            vp, default_group=def_grp, default_period=def_per, advanced_visible=advanced_visible
        )

    _register_conversation_and_visidata(subparsers, advanced_visible=advanced_visible)
    _register_admin_subparsers(subparsers)
    return parser


def render_shell_completions(shell: str) -> str:
    """Return a concise shell completion script for `bash`, `zsh`, or `fish`."""
    nouns = "report conversation query visidata config metrics schema"
    if shell == "fish":
        return f"complete -c wallace -f -n '__fish_use_subcommand' -a '{nouns}'\n"
    if shell == "zsh":
        return (
            "#compdef wallace\n"
            f"_wallace() {{ compadd -- {nouns} --help --help-all --config; }}\n"
            "compdef _wallace wallace\n"
        )
    return f'complete -W "{nouns} --help --help-all --version --config" wallace\n'


# endregion
