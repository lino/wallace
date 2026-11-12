"""Model name normalization, family matching, and per-turn USD cost calculation."""

from __future__ import annotations

import re
from collections.abc import Mapping

from wallace.config import TOKENS_PER_MILLION, ModelPricing

_HUMAN_MODEL_RE = re.compile(r"[^a-z0-9.+-]+")


def normalize_model_name(raw_model: str | None) -> str:
    """Normalize a raw or human-readable model label into a canonical slug.

    Args:
        raw_model: Raw model identifier from `gen_metadata` or `<USER_SETTINGS_CHANGE>`.

    Returns:
        Lowercase canonical slug such as `"gemini-4-argon-high"` or `"unknown"`.
    """
    if not raw_model:
        return "unknown"
    cleaned = raw_model.strip().lower()
    if not cleaned or cleaned == "none":
        return "unknown"
    slug = _HUMAN_MODEL_RE.sub("-", cleaned).strip("-")
    return slug or "unknown"


def resolve_model_pricing(
    model_name: str,
    pricing_table: Mapping[str, ModelPricing],
) -> ModelPricing:
    """Resolve `ModelPricing` by exact key, family fallback, or `"unknown"` rate."""
    normalized = normalize_model_name(model_name)
    if normalized in pricing_table:
        return pricing_table[normalized]

    family_key = _infer_family_key(normalized)
    if family_key and family_key in pricing_table:
        return pricing_table[family_key]

    return pricing_table.get("unknown", ModelPricing(1.0, 0.1, 5.0))


def _infer_family_key(model: str) -> str | None:
    """Map an arbitrary model slug to a `family:*` fallback key."""
    if "claude" in model and "opus" in model:
        return "family:claude-opus"
    if "claude" in model and ("sonnet" in model or "haiku" in model):
        return "family:claude-sonnet"
    if model.startswith("gemini-4"):
        return "family:gemini-4"
    if "gemini" in model and "flash" in model:
        return "family:gemini-flash"
    if "gemini" in model:
        return "family:gemini-pro"
    return None


def calculate_turn_cost(
    *,
    model: str,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    pricing_table: Mapping[str, ModelPricing],
) -> float:
    """Compute estimated USD cost for a single turn from uncached, cached, and output tokens."""
    rate = resolve_model_pricing(model, pricing_table)
    input_cost = (max(input_tokens, 0) / TOKENS_PER_MILLION) * rate.input_per_million
    cached_cost = (max(cached_input_tokens, 0) / TOKENS_PER_MILLION) * rate.cached_input_per_million
    output_cost = (max(output_tokens, 0) / TOKENS_PER_MILLION) * rate.output_per_million
    return input_cost + cached_cost + output_cost
