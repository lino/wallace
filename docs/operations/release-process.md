# PyPI Release Process

## Overview

**What you will learn:**

- How to configure PyPI Trusted Publishing (OIDC) for `wallace-audit`.
- How to cut and publish a verified release to PyPI and GitHub Releases.
- How to troubleshoot tag/version mismatches or Trusted Publisher rejections.

`wallace-audit` publishes source distributions (`sdist`) and wheels (`bdist_wheel`) from GitHub Actions using OpenID Connect (OIDC) Trusted Publishing—no long-lived PyPI API tokens are stored in repository secrets.

## Prerequisites

- Maintainer access to `lino/wallace` on GitHub.
- A PyPI account with permission to register `wallace-audit`.
- A green `CI` workflow run on the `main` commit you plan to release.

## One-Time PyPI Trusted Publisher Setup

1. Sign in to [PyPI](https://pypi.org/) and open **Your projects → Publishing** (or **Account settings → Publishing** for a pending publisher on first release).
2. Add a **GitHub Actions** pending publisher with these exact values:
   - **PyPI Project Name**: `wallace-audit`
   - **Owner**: `lino`
   - **Repository name**: `wallace`
   - **Workflow name**: `release.yml`
   - **Environment name**: `pypi`
3. Ensure the `pypi` environment exists in GitHub (**Settings → Environments → pypi**).

## Release Steps

1. Update `__version__` in `src/wallace/__init__.py` (this is the single source of truth read by Hatchling).
2. Run `uv lock` if dependencies changed, then verify locally:
   ```bash
   mise run verify
   mise run build
   mise run docs
   ```
3. Commit and push to `main`, and **wait for the `CI` workflow to pass completely** before tagging.
4. Create and push the matching version tag (must match `v<__version__>`):
   ```bash
   git tag -a v0.1.0 -m "Release v0.1.0"
   git push origin v0.1.0
   ```
5. Monitor the `Release` workflow in GitHub Actions. Once it completes, verify the package on [PyPI](https://pypi.org/project/wallace-audit/) and the generated GitHub Release.

## Expected Outcome

- `wallace-audit` is published to PyPI with both `.tar.gz` and `.whl` artifacts.
- `uv tool install wallace-audit` installs the `wallace` executable.
- A matching GitHub Release is created with release notes and attached distribution files.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Tag vX.Y.Z does not match wallace.__version__` | Tag differs from `src/wallace/__init__.py` | Update `__version__`, let CI pass on `main`, and tag the matching version |
| `403` / Trusted Publisher error on PyPI | Pending publisher fields mismatch | Confirm owner `lino`, repo `wallace`, workflow `release.yml`, environment `pypi` |
