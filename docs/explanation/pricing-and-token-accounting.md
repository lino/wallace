# Pricing and Token Accounting

Understanding how `wallace` turns raw session logs into token counts and USD figures helps you trust audit totals and diagnose unexpected `N/A` or `~` markers.

## Offline Pricing via `genai-prices`

`wallace` never makes network calls to fetch model pricing. Instead, it bundles the offline catalog from [`genai-prices`](https://github.com/pydantic/genai-prices). Updating the `genai-prices` dependency refreshes default rates across providers.

Before looking up a model, `wallace` normalizes raw provider labels into lowercase canonical slugs (for example, `"Gemini 4 Argon (High)"` becomes `"gemini-4-argon-high"`). Known reasoning-effort suffixes (`-low`, `-medium`, `-high`) map back to their underlying API model in the catalog so effort tiers share the API's published rate.

## How Local Overrides Merge With the Catalog

When a `[pricing."<model-id>"]` table exists in `config.toml`, `wallace` resolves overrides in this order:

1. Exact canonical model slug (for example `"gpt-5"`).
1. Configured model family key (such as `"family:claude-opus"` or `"family:gemini-4"`).
1. Bundled `genai-prices` catalog entry.
1. Configured `"unknown"` fallback table, if defined.

Partial overrides merge cleanly onto the catalog entry. For example, if you override only `cached_input_per_million` for a catalog model, `wallace` keeps the catalog's `input_per_million` and `output_per_million` rates.

## Unpriced Usage (`N/A`, `null`, and `NaN`)

If a turn uses a model absent from both the catalog and your local overrides (or omits a required token category rate), `wallace` refuses to silently bill it as `$0.00`. Instead, it marks the turn's cost as unpriced (`NaN` internally) and propagates that state to any aggregate total containing it:

- **Terminal tables (`table`, `plain`)**: Shows `N/A`.
- **JSON and JSONL (`json`, `jsonl`)**: Emits `null`.
- **CSV and TSV (`csv`, `tsv`)**: Leaves the `cost_usd` cell empty.
- **SQLite (`sqlite`)**: Stores `NULL`.
- **Prometheus (`wallace_cost_usd_total`)**: Reports `NaN`.

Token counts remain exact and fully aggregated even when USD cost is unpriced.

## Provider-Specific Billing Nuances

- **Grok CLI (`costUsdTicks`)**: Grok `usage.json` records exact integer billing ticks (`10,000,000,000` ticks = `$1.00` USD). When present, `wallace` converts these ticks directly rather than re-estimating from rates.
- **OpenAI Codex**: Codex rollouts record token counts, not subscription invoices. `wallace` estimates equivalent standard API costs from those token counts; actual subscription charges may differ.
- **Thinking Tokens**: Reasoning tokens generated before visible output are counted inside `output_tokens` and tracked separately in `thinking_tokens` for visibility.

## Exact Tokens vs. Estimated Tokens (`~`)

Most local sessions record exact API usage blocks per turn. However, some exported transcripts omit raw usage metadata.

When raw usage is missing, `wallace` computes a deterministic text-based subword approximation (`estimate_text_tokens`) from message content. Any conversation or turn relying on this fallback is flagged with `is_estimated = true` in JSON and rendered with a leading `~` (for example `~1,420`) in the TUI browser so you always know which counts are approximate.
