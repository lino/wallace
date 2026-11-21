"""Configuration models, default pricing tables, and TOML/environment loaders."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

# region Constants & Defaults

ENV_CONFIG_PATH = "WALLACE_CONFIG"
ENV_IDE_DIR = "WALLACE_IDE_DIR"
ENV_CLI_DIR = "WALLACE_CLI_DIR"
ENV_CLAUDE_DIR = "WALLACE_CLAUDE_DIR"
ENV_GROK_DIR = "WALLACE_GROK_DIR"
ENV_CODEX_DIR = "WALLACE_CODEX_DIR"
ENV_BRAIN_DIRS = "WALLACE_BRAIN_DIRS"
ENV_METRICS_HOST = "WALLACE_METRICS_HOST"
ENV_METRICS_PORT = "WALLACE_METRICS_PORT"

DEFAULT_REL_CONFIG_PATH = Path(".config") / "wallace" / "config.toml"
DEFAULT_REL_IDE_DIR = Path(".gemini") / "antigravity"
DEFAULT_REL_CLI_DIR = Path(".gemini") / "antigravity-cli"
DEFAULT_REL_CLAUDE_DIR = Path(".claude")
DEFAULT_REL_GROK_DIR = Path(".grok")
DEFAULT_REL_CODEX_DIR = Path(".codex")
DEFAULT_METRICS_HOST = "127.0.0.1"
DEFAULT_METRICS_PORT = 9464
GROK_TICKS_PER_USD = 10_000_000_000.0

DEFAULT_IGNORED_BRANCHES: tuple[str, ...] = (
    "main",
    "master",
    "develop",
    "dev",
    "trunk",
    "HEAD",
)
DEFAULT_WP_REGEX = r"(?i)\b((?:(?!(?:ARBEITER|SUBAGENT|WORKER)-)[A-Z][A-Z0-9]+-)?WP-?\d+)\b"

# endregion


# region Data Models


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """Per-million-token USD pricing rates for an LLM identifier or family.

    Attributes:
        input_per_million: USD rate per 1,000,000 uncached input tokens.
        cached_input_per_million: USD rate per 1,000,000 cache-read input tokens.
        output_per_million: USD rate per 1,000,000 output (including thinking) tokens.
    """

    input_per_million: float | None = None
    cached_input_per_million: float | None = None
    output_per_million: float | None = None


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Runtime configuration governing session directories, feature extraction, and pricing.

    Attributes:
        ide_dir: Optional Antigravity IDE root directory (containing `brain/`).
        cli_dir: Optional Antigravity CLI root directory (containing `brain/`).
        claude_dir: Optional Claude Code local session directory (default `~/.claude`).
        grok_dir: Optional Grok CLI local session directory (default `~/.grok`).
        codex_dir: Optional Codex home or rollout path.
        extra_brain_dirs: Additional standalone `brain/` directories to scan.
        ignored_branches: Default git branch names excluded from feature grouping.
        work_package_pattern: Regular expression extracting Work Package IDs.
        metrics_host: Default bind address for the Prometheus HTTP exporter.
        metrics_port: Default TCP port for the Prometheus HTTP exporter.
        pricing: Local rate overrides by model name or `family:*` key.
    """

    ide_dir: Path | None = field(default_factory=lambda: Path.home() / DEFAULT_REL_IDE_DIR)
    cli_dir: Path | None = field(default_factory=lambda: Path.home() / DEFAULT_REL_CLI_DIR)
    claude_dir: Path | None = None
    grok_dir: Path | None = None
    extra_brain_dirs: tuple[Path, ...] = ()
    ignored_branches: tuple[str, ...] = DEFAULT_IGNORED_BRANCHES
    work_package_pattern: str = DEFAULT_WP_REGEX
    metrics_host: str = DEFAULT_METRICS_HOST
    metrics_port: int = DEFAULT_METRICS_PORT
    pricing: dict[str, ModelPricing] = field(default_factory=dict)
    codex_dir: Path | None = None


# endregion


# region Configuration Loading


def _resolve_optional_dir(raw: str | None, fallback: Path | None) -> Path | None:
    """Resolve an optional path string, treating empty strings as disabled."""
    if raw is None:
        return fallback
    cleaned = raw.strip()
    if not cleaned:
        return None
    return Path(cleaned).expanduser()


def _parse_pricing_overrides(raw_pricing: object, base: dict[str, ModelPricing]) -> None:
    """Merge `[pricing]` TOML tables into `base` pricing dictionary in place."""
    if not isinstance(raw_pricing, Mapping):
        return
    for model_key, entry in raw_pricing.items():
        if not isinstance(entry, Mapping):
            continue
        overrides = {
            key: float(entry[key])
            for key in ("input_per_million", "cached_input_per_million", "output_per_million")
            if key in entry
        }
        if overrides:
            base[str(model_key)] = ModelPricing(**overrides)


def _parse_paths_section(
    sec: object,
    ide_dir: Path | None,
    cli_dir: Path | None,
    claude_dir: Path | None,
    grok_dir: Path | None,
    extra_dirs: list[Path],
) -> tuple[Path | None, Path | None, Path | None, Path | None, list[Path]]:
    """Extract `(ide_dir, cli_dir, claude_dir, grok_dir, extra_dirs)` from `[paths]` TOML."""
    if not isinstance(sec, Mapping):
        return ide_dir, cli_dir, claude_dir, grok_dir, extra_dirs
    if "ide_dir" in sec:
        ide_dir = _resolve_optional_dir(str(sec["ide_dir"]), ide_dir)
    if "cli_dir" in sec:
        cli_dir = _resolve_optional_dir(str(sec["cli_dir"]), cli_dir)
    if "claude_dir" in sec:
        claude_dir = _resolve_optional_dir(str(sec["claude_dir"]), claude_dir)
    if "grok_dir" in sec:
        grok_dir = _resolve_optional_dir(str(sec["grok_dir"]), grok_dir)
    raw_extra = sec.get("extra_brain_dirs")
    if isinstance(raw_extra, list):
        extra_dirs = [Path(str(p)).expanduser() for p in raw_extra if str(p).strip()]
    return ide_dir, cli_dir, claude_dir, grok_dir, extra_dirs


def _parse_features_section(
    sec: object,
    ignored_branches: tuple[str, ...],
    wp_pattern: str,
) -> tuple[tuple[str, ...], str]:
    """Extract `(ignored_branches, wp_pattern)` from a `[features]` TOML section."""
    if not isinstance(sec, Mapping):
        return ignored_branches, wp_pattern
    raw_ignored = sec.get("ignored_branches")
    if isinstance(raw_ignored, list):
        ignored_branches = tuple(str(b) for b in raw_ignored)
    if "work_package_pattern" in sec:
        wp_pattern = str(sec["work_package_pattern"])
    return ignored_branches, wp_pattern


def _apply_toml_document(
    doc: Mapping[str, object],
    base: AppConfig,
) -> AppConfig:
    """Build an `AppConfig` by applying parsed TOML sections over `base`."""
    ide_dir, cli_dir, claude_dir, grok_dir, extra_dirs = _parse_paths_section(
        doc.get("paths"),
        base.ide_dir,
        base.cli_dir,
        base.claude_dir,
        base.grok_dir,
        list(base.extra_brain_dirs),
    )
    codex_dir = base.codex_dir
    paths = doc.get("paths")
    if isinstance(paths, Mapping) and "codex_dir" in paths:
        codex_dir = _resolve_optional_dir(str(paths["codex_dir"]), codex_dir)
    ignored_branches, wp_pattern = _parse_features_section(
        doc.get("features"), base.ignored_branches, base.work_package_pattern
    )
    metrics_host = base.metrics_host
    metrics_port = base.metrics_port
    metrics_sec = doc.get("metrics")
    if isinstance(metrics_sec, Mapping):
        metrics_host = str(metrics_sec.get("host", metrics_host))
        metrics_port = int(str(metrics_sec.get("port", metrics_port)))

    pricing = dict(base.pricing)
    _parse_pricing_overrides(doc.get("pricing"), pricing)
    return AppConfig(
        ide_dir=ide_dir,
        cli_dir=cli_dir,
        claude_dir=claude_dir,
        grok_dir=grok_dir,
        codex_dir=codex_dir,
        extra_brain_dirs=tuple(extra_dirs),
        ignored_branches=ignored_branches,
        work_package_pattern=wp_pattern,
        metrics_host=metrics_host,
        metrics_port=metrics_port,
        pricing=pricing,
    )


def load_config(
    config_path: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> AppConfig:
    """Load `AppConfig` from default paths, optional TOML file, and `WALLACE_*` env vars.

    Args:
        config_path: Explicit TOML file path; falls back to `WALLACE_CONFIG` or XDG default.
        env: Environment dictionary; defaults to `os.environ`.

    Returns:
        Resolved `AppConfig` instance.
    """
    environ = os.environ if env is None else env
    home = Path.home()
    resolved_cfg = config_path
    if resolved_cfg is None:
        env_cfg = environ.get(ENV_CONFIG_PATH)
        resolved_cfg = Path(env_cfg).expanduser() if env_cfg else home / DEFAULT_REL_CONFIG_PATH

    cfg = AppConfig(
        claude_dir=home / DEFAULT_REL_CLAUDE_DIR,
        grok_dir=home / DEFAULT_REL_GROK_DIR,
        codex_dir=_resolve_optional_dir(environ.get("CODEX_HOME"), home / DEFAULT_REL_CODEX_DIR),
    )
    if resolved_cfg.is_file():
        doc = tomllib.loads(resolved_cfg.read_text(encoding="utf-8"))
        cfg = _apply_toml_document(doc, cfg)

    ide_dir = _resolve_optional_dir(environ.get(ENV_IDE_DIR), cfg.ide_dir)
    cli_dir = _resolve_optional_dir(environ.get(ENV_CLI_DIR), cfg.cli_dir)
    claude_dir = _resolve_optional_dir(environ.get(ENV_CLAUDE_DIR), cfg.claude_dir)
    grok_dir = _resolve_optional_dir(environ.get(ENV_GROK_DIR), cfg.grok_dir)
    codex_dir = _resolve_optional_dir(environ.get(ENV_CODEX_DIR), cfg.codex_dir)
    extra_dirs = list(cfg.extra_brain_dirs)
    if ENV_BRAIN_DIRS in environ and environ[ENV_BRAIN_DIRS].strip():
        extra_dirs = [
            Path(part).expanduser()
            for part in environ[ENV_BRAIN_DIRS].split(os.pathsep)
            if part.strip()
        ]
    metrics_host = environ.get(ENV_METRICS_HOST, cfg.metrics_host)
    metrics_port = int(environ.get(ENV_METRICS_PORT, str(cfg.metrics_port)))
    return AppConfig(
        ide_dir=ide_dir,
        cli_dir=cli_dir,
        claude_dir=claude_dir,
        grok_dir=grok_dir,
        codex_dir=codex_dir,
        extra_brain_dirs=tuple(extra_dirs),
        ignored_branches=cfg.ignored_branches,
        work_package_pattern=wp_pattern_or_default(cfg.work_package_pattern),
        metrics_host=metrics_host,
        metrics_port=metrics_port,
        pricing=cfg.pricing,
    )


def wp_pattern_or_default(pattern: str) -> str:
    """Return `pattern` when non-empty, else `DEFAULT_WP_REGEX`."""
    return pattern if pattern.strip() else DEFAULT_WP_REGEX


# endregion


# region Serialization


def render_config_toml(config: AppConfig) -> str:
    """Serialize an `AppConfig` to a commented, human-editable TOML document."""
    ide_str = str(config.ide_dir) if config.ide_dir is not None else ""
    cli_str = str(config.cli_dir) if config.cli_dir is not None else ""
    claude_str = str(config.claude_dir) if config.claude_dir is not None else ""
    grok_str = str(config.grok_dir) if config.grok_dir is not None else ""
    codex_str = str(config.codex_dir) if config.codex_dir is not None else ""
    extra_items = ", ".join(f'"{p}"' for p in config.extra_brain_dirs)
    ignored_items = ", ".join(f'"{b}"' for b in config.ignored_branches)
    escaped_wp = config.work_package_pattern.replace("\\", "\\\\")

    lines = [
        "# wallace configuration file",
        "[paths]",
        f'ide_dir = "{ide_str}"',
        f'cli_dir = "{cli_str}"',
        f'claude_dir = "{claude_str}"',
        f'grok_dir = "{grok_str}"',
        f'codex_dir = "{codex_str}"',
        f"extra_brain_dirs = [{extra_items}]",
        "",
        "[features]",
        f"ignored_branches = [{ignored_items}]",
        f'work_package_pattern = "{escaped_wp}"',
        "",
        "[metrics]",
        f'host = "{config.metrics_host}"',
        f"port = {config.metrics_port}",
        "",
    ]
    lines.extend(('# Add a [pricing."model-id"] table to override catalog rates.', ""))
    for model_key, rate in sorted(config.pricing.items()):
        lines.append(f'[pricing."{model_key}"]')
        for name, value in (
            ("input_per_million", rate.input_per_million),
            ("cached_input_per_million", rate.cached_input_per_million),
            ("output_per_million", rate.output_per_million),
        ):
            if value is not None:
                lines.append(f"{name} = {value}")
        lines.append("")
    return "\n".join(lines)


# endregion
