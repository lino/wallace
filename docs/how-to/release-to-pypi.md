# Release to PyPI

## Overview

**What you will learn:**

- Configure PyPI OpenID Connect (OIDC) Trusted Publishing for `wallace-audit`.
- Verify, tag, and publish a release to PyPI and GitHub Releases.

`wallace-audit` publishes source distributions (`sdist`) and wheels (`bdist_wheel`) from GitHub Actions using OIDC Trusted Publishing. No long-lived PyPI API tokens are stored in repository secrets.

## Prerequisites

- Maintainer access to `lino/wallace` on GitHub.
- A PyPI account with permission to manage `wallace-audit`.
- A green `CI` workflow run on the `main` commit you plan to release.

## One-Time PyPI Trusted Publisher Setup

1. Sign in to [PyPI](https://pypi.org/) and open **Your projects -> Publishing** (or **Account settings -> Publishing** for a first-time pending publisher).
1. Add a **GitHub Actions** publisher with these exact values:
   - **PyPI Project Name**: `wallace-audit`
   - **Owner**: `lino`
   - **Repository name**: `wallace`
   - **Workflow name**: `release.yml`
   - **Environment name**: `pypi`
1. Verify that the `pypi` environment exists in GitHub (**Settings -> Environments -> pypi**).

## Cut a Verified Release

1. Update `__version__` in `src/wallace/__init__.py` (the single source of truth read by Hatchling).
1. Run `uv lock` if dependencies changed, then verify locally:
   ```bash
   mise run verify
   mise run build
   mise run docs
   ```
1. Commit and push to `main`. Wait for the `CI` workflow to pass completely before tagging.
1. Create and push the matching annotated tag (`v<__version__>`):
   ```bash
   git tag -a v0.1.0 -m "Release v0.1.0"
   git push origin v0.1.0
   ```
1. Monitor the `Release` workflow in GitHub Actions and verify the published artifacts on [PyPI](https://pypi.org/project/wallace-audit/).

## Expected Outcome

- `wallace-audit` is published to PyPI with both `.tar.gz` and `.whl` artifacts.
- `uv tool install wallace-audit` installs the `wallace` executable.
- A matching GitHub Release is created with release notes and attached distribution files.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Tag vX.Y.Z does not match wallace.__version__` | Git tag differs from `src/wallace/__init__.py` | Update `__version__`, let `CI` pass on `main`, and push the matching tag. |
| `403` / Trusted Publisher error on PyPI | Publisher configuration fields do not match | Verify owner `lino`, repo `wallace`, workflow `release.yml`, and environment `pypi`. |
