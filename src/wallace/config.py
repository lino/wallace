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
ENV_BRAIN_DIRS = "WALLACE_BRAIN_DIRS"
ENV_METRICS_HOST = "WALLACE_METRICS_HOST"
ENV_METRICS_PORT = "WALLACE_METRICS_PORT"

DEFAULT_REL_CONFIG_PATH = Path(".config") / "wallace" / "config.toml"
DEFAULT_REL_IDE_DIR = Path(".gemini") / "antigravity"
DEFAULT_REL_CLI_DIR = Path(".gemini") / "antigravity-cli"
DEFAULT_METRICS_HOST = "127.0.0.1"
DEFAULT_METRICS_PORT = 9464
TOKENS_PER_MILLION = 1_000_000.0

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

    input_per_million: float
    cached_input_per_million: float
    output_per_million: float


def default_pricing_table() -> dict[str, ModelPricing]:
    """Return editable default USD per-1M-token rates for Antigravity models."""
    return {
        "gemini-4-carbon": ModelPricing(1.25, 0.125, 10.00),
        "gemini-4-argon": ModelPricing(1.25, 0.125, 10.00),
        "gemini-4-argon-high": ModelPricing(1.25, 0.125, 10.00),
        "gemini-4-argon-medium": ModelPricing(1.25, 0.125, 10.00),
        "gemini-4-argon-low": ModelPricing(1.25, 0.125, 10.00),
        "gemini-4-argon-d": ModelPricing(1.25, 0.125, 10.00),
        "gemini-4-argon-w": ModelPricing(1.25, 0.125, 10.00),
        "gemini-3.8-flash": ModelPricing(0.30, 0.03, 2.50),
        "gemini-3.8-flash-tiered": ModelPricing(0.30, 0.03, 2.50),
        "gemini-3.7-flash": ModelPricing(0.15, 0.0375, 0.60),
        "gemini-3.5-flash-lite": ModelPricing(0.10, 0.025, 0.40),
        "claude-opus-5-5-high": ModelPricing(15.00, 1.50, 75.00),
        "claude-opus-5-5-medium": ModelPricing(15.00, 1.50, 75.00),
        "claude-opus-5-5-low": ModelPricing(15.00, 1.50, 75.00),
        "claude-sonnet-5-5-high": ModelPricing(3.00, 0.30, 15.00),
        "claude-sonnet-5-5-medium": ModelPricing(3.00, 0.30, 15.00),
        "claude-sonnet-5-5-low": ModelPricing(3.00, 0.30, 15.00),
        "family:claude-opus": ModelPricing(15.00, 1.50, 75.00),
        "family:claude-sonnet": ModelPricing(3.00, 0.30, 15.00),
        "family:gemini-4": ModelPricing(1.25, 0.125, 10.00),
        "family:gemini-flash": ModelPricing(0.30, 0.03, 2.50),
        "family:gemini-pro": ModelPricing(1.25, 0.125, 10.00),
        "unknown": ModelPricing(1.00, 0.10, 5.00),
    }


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Runtime configuration governing brain directories, feature extraction, and pricing.

    Attributes:
        ide_dir: Optional Antigravity IDE root directory (containing `brain/`).
        cli_dir: Optional Antigravity CLI root directory (containing `brain/`).
        extra_brain_dirs: Additional standalone `brain/` directories to scan.
        ignored_branches: Default git branch names excluded from feature grouping.
        work_package_pattern: Regular expression extracting Work Package IDs.
        metrics_host: Default bind address for the Prometheus HTTP exporter.
        metrics_port: Default TCP port for the Prometheus HTTP exporter.
        pricing: Mapping of model names and `family:*` keys to `ModelPricing`.
    """

    ide_dir: Path | None = field(default_factory=lambda: Path.home() / DEFAULT_REL_IDE_DIR)
    cli_dir: Path | None = field(default_factory=lambda: Path.home() / DEFAULT_REL_CLI_DIR)
    extra_brain_dirs: tuple[Path, ...] = ()
    ignored_branches: tuple[str, ...] = DEFAULT_IGNORED_BRANCHES
    work_package_pattern: str = DEFAULT_WP_REGEX
    metrics_host: str = DEFAULT_METRICS_HOST
    metrics_port: int = DEFAULT_METRICS_PORT
    pricing: dict[str, ModelPricing] = field(default_factory=default_pricing_table)


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
        fallback = base.get(str(model_key), base["unknown"])
        base[str(model_key)] = ModelPricing(
            input_per_million=float(entry.get("input_per_million", fallback.input_per_million)),
            cached_input_per_million=float(
                entry.get("cached_input_per_million", fallback.cached_input_per_million)
            ),
            output_per_million=float(entry.get("output_per_million", fallback.output_per_million)),
        )


def _parse_paths_section(
    sec: object,
    ide_dir: Path | None,
    cli_dir: Path | None,
    extra_dirs: list[Path],
) -> tuple[Path | None, Path | None, list[Path]]:
    """Extract `(ide_dir, cli_dir, extra_dirs)` from a `[paths]` TOML section."""
    if not isinstance(sec, Mapping):
        return ide_dir, cli_dir, extra_dirs
    if "ide_dir" in sec:
        ide_dir = _resolve_optional_dir(str(sec["ide_dir"]), ide_dir)
    if "cli_dir" in sec:
        cli_dir = _resolve_optional_dir(str(sec["cli_dir"]), cli_dir)
    raw_extra = sec.get("extra_brain_dirs")
    if isinstance(raw_extra, list):
        extra_dirs = [Path(str(p)).expanduser() for p in raw_extra if str(p).strip()]
    return ide_dir, cli_dir, extra_dirs


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
    *,
    ide_dir: Path | None,
    cli_dir: Path | None,
    extra_dirs: list[Path],
    ignored_branches: tuple[str, ...],
    wp_pattern: str,
    metrics_host: str,
    metrics_port: int,
    pricing: dict[str, ModelPricing],
) -> AppConfig:
    """Build an `AppConfig` by applying parsed TOML sections over defaults."""
    ide_dir, cli_dir, extra_dirs = _parse_paths_section(
        doc.get("paths"), ide_dir, cli_dir, extra_dirs
    )
    ignored_branches, wp_pattern = _parse_features_section(
        doc.get("features"), ignored_branches, wp_pattern
    )
    metrics_sec = doc.get("metrics")
    if isinstance(metrics_sec, Mapping):
        metrics_host = str(metrics_sec.get("host", metrics_host))
        metrics_port = int(str(metrics_sec.get("port", metrics_port)))

    _parse_pricing_overrides(doc.get("pricing"), pricing)
    return AppConfig(
        ide_dir=ide_dir,
        cli_dir=cli_dir,
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
    resolved_cfg = config_path
    if resolved_cfg is None:
        env_cfg = environ.get(ENV_CONFIG_PATH)
        resolved_cfg = (
            Path(env_cfg).expanduser() if env_cfg else Path.home() / DEFAULT_REL_CONFIG_PATH
        )

    cfg = AppConfig()
    if resolved_cfg.is_file():
        doc = tomllib.loads(resolved_cfg.read_text(encoding="utf-8"))
        cfg = _apply_toml_document(
            doc,
            ide_dir=cfg.ide_dir,
            cli_dir=cfg.cli_dir,
            extra_dirs=list(cfg.extra_brain_dirs),
            ignored_branches=cfg.ignored_branches,
            wp_pattern=cfg.work_package_pattern,
            metrics_host=cfg.metrics_host,
            metrics_port=cfg.metrics_port,
            pricing=dict(cfg.pricing),
        )

    ide_dir = _resolve_optional_dir(environ.get(ENV_IDE_DIR), cfg.ide_dir)
    cli_dir = _resolve_optional_dir(environ.get(ENV_CLI_DIR), cfg.cli_dir)
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
        extra_brain_dirs=tuple(extra_dirs),
        ignored_branches=cfg.ignored_branches,
        work_package_pattern=cfg.work_package_pattern,
        metrics_host=metrics_host,
        metrics_port=metrics_port,
        pricing=cfg.pricing,
    )


# endregion


# region Serialization


def render_config_toml(config: AppConfig) -> str:
    """Serialize an `AppConfig` to a commented, human-editable TOML document."""
    ide_str = str(config.ide_dir) if config.ide_dir is not None else ""
    cli_str = str(config.cli_dir) if config.cli_dir is not None else ""
    extra_items = ", ".join(f'"{p}"' for p in config.extra_brain_dirs)
    ignored_items = ", ".join(f'"{b}"' for b in config.ignored_branches)
    escaped_wp = config.work_package_pattern.replace("\\", "\\\\")

    lines = [
        "# wallace configuration file",
        "[paths]",
        f'ide_dir = "{ide_str}"',
        f'cli_dir = "{cli_str}"',
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
    for model_key, rate in sorted(config.pricing.items()):
        lines.extend(
            [
                f'[pricing."{model_key}"]',
                f"input_per_million = {rate.input_per_million}",
                f"cached_input_per_million = {rate.cached_input_per_million}",
                f"output_per_million = {rate.output_per_million}",
                "",
            ]
        )
    return "\n".join(lines)


# endregion
