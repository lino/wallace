# Configure Pricing and Session Paths

## Overview

**What you will learn:**

- Generate and edit the TOML configuration file (`~/.config/wallace/config.toml`).
- Override bundled `genai-prices` catalog rates for specific models or model families.
- Point `wallace` to custom provider directories or disable discovery for a provider.

`wallace` works out of the box with default session paths and the bundled offline `genai-prices` catalog. Use configuration overrides when you run enterprise model rates, store sessions in non-standard folders, or audit exported archives.

## Prerequisites

- `wallace` installed on your `PATH`.

## Initialize and Inspect Configuration

1. Write a starter TOML file to the default XDG location:
   ```bash
   wallace config init --output ~/.config/wallace/config.toml
   ```
1. Print the active merged configuration (defaults + TOML + environment variables):
   ```bash
   wallace config show
   ```

## Override Model Pricing

1. Open `~/.config/wallace/config.toml` in your editor.
1. Add a `[pricing."<model-id>"]` table with any subset of `input_per_million`, `cached_input_per_million`, and `output_per_million`:
   ```toml
   [pricing."gpt-5"]
   input_per_million = 1.25
   cached_input_per_million = 0.125
   output_per_million = 10.0

   [pricing."my-internal-model"]
   input_per_million = 0.50
   cached_input_per_million = 0.05
   output_per_million = 2.00
   ```
1. Run `wallace report models` to verify the updated USD costs.

> **Upgrading from an older config?** Older generated config files populated default `[pricing]` tables. Delete any entries you want `wallace` to resolve automatically from the bundled `genai-prices` catalog.

## Override or Disable Provider Paths

1. Point a provider to a custom directory via TOML (`[paths]`), environment variable, or CLI flag:
   ```bash
   wallace report monthly --codex-dir /mnt/archive/codex
   ```
1. Disable discovery for a provider by setting its environment variable or TOML key to an empty string:
   ```bash
   WALLACE_CODEX_DIR="" wallace report sources
   ```
1. Scan standalone exported Antigravity brain directories without touching default paths:
   ```bash
   wallace --brain-dir /tmp/exported-brains report summary
   ```

## Expected Outcome

`wallace config show` reflects your custom paths and `[pricing]` tables. Reports compute USD costs using your overrides first and fall back to the bundled `genai-prices` catalog for all other models.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Configuration file already exists` | `config init` protects existing files from accidental overwrite | Pass `--force` to overwrite the target file intentionally. |
| Cost shows `N/A` in terminal or `null` in JSON | One or more contributing turns used a model absent from the catalog | Add a `[pricing."<model-id>"]` table with rates for every token category the model uses. |
| `TOTAL 0` rows in output | Default directories do not contain sessions | Pass `--ide-dir`, `--cli-dir`, `--claude-dir`, `--grok-dir`, or `--codex-dir`, or set `WALLACE_*_DIR`. |
