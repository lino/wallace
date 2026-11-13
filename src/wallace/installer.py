"""Configurable user-PATH launcher shim installer (`wallace install`)."""

from __future__ import annotations

import os
import shlex
from collections.abc import Mapping
from pathlib import Path

ENV_BIN_DIR = "WALLACE_BIN_DIR"
DEFAULT_REL_BIN_DIR = Path(".local") / "bin"
LAUNCHER_FILENAME = "wallace"
LAUNCHER_MODE = 0o755


def resolve_repo_root() -> Path:
    """Resolve the `wallace` checkout root dynamically from package location."""
    return Path(__file__).resolve().parents[2]


def resolve_bin_dir(
    bin_dir: Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """Resolve target `PATH` directory (`--bin-dir` -> `WALLACE_BIN_DIR` -> `~/.local/bin`)."""
    if bin_dir is not None:
        return bin_dir.expanduser()
    environ = os.environ if env is None else env
    raw_env = environ.get(ENV_BIN_DIR, "").strip()
    if raw_env:
        return Path(raw_env).expanduser()
    return (home or Path.home()) / DEFAULT_REL_BIN_DIR


def render_launcher_script(repo_root: Path) -> str:
    """Render a POSIX `sh` launcher delegating to `.venv/bin/wallace` or `uv run`."""
    quoted_root = shlex.quote(str(repo_root.resolve()))
    return (
        "#!/usr/bin/env sh\n"
        "# Thin executable launcher for the wallace token and cost auditor.\n"
        "set -eu\n"
        f'REPO_ROOT="${{WALLACE_REPO:-{quoted_root}}}"\n'
        'if [ -x "$REPO_ROOT/.venv/bin/wallace" ]; then\n'
        '  exec "$REPO_ROOT/.venv/bin/wallace" "$@"\n'
        "fi\n"
        'exec uv run --project "$REPO_ROOT" wallace "$@"\n'
    )


def install_launcher(
    bin_dir: Path | None = None,
    *,
    repo_root: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> Path:
    """Write an executable `wallace` launcher shim into the resolved `bin_dir`."""
    target_dir = resolve_bin_dir(bin_dir, env=env)
    target_dir.mkdir(parents=True, exist_ok=True)
    launcher_path = target_dir / LAUNCHER_FILENAME
    root = repo_root if repo_root is not None else resolve_repo_root()
    launcher_path.write_text(render_launcher_script(root), encoding="utf-8")
    launcher_path.chmod(LAUNCHER_MODE)
    return launcher_path
