"""Model name normalization, family matching, token estimation, and USD cost calculation."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from decimal import Decimal

from genai_prices import Usage, calc_price
from genai_prices.types import ModelPrice

from wallace.config import ModelPricing

_HUMAN_MODEL_RE = re.compile(r"[^a-z0-9.+-]+")
_TOKEN_PIECE_RE = re.compile(r"[A-Za-z0-9]+|[^\sA-Za-z0-9]")
_CHARS_PER_SUBWORD = 4.0
_BYTES_PER_TOKEN = 4.0


def normalize_model_name(raw_model: str | None) -> str:
    """Normalize a raw or human-readable model label into a canonical slug.

    Args:
        raw_model: Raw model identifier from provider metadata or `<USER_SETTINGS_CHANGE>`.

    Returns:
        Lowercase canonical slug such as `"gemini-4-argon-high"` or `"unknown"`.
    """
    if not raw_model:
        return "unknown"
    cleaned = raw_model.strip().lower()
    if not cleaned or cleaned in ("none", "<synthetic>", "synthetic"):
        return "unknown"
    slug = _HUMAN_MODEL_RE.sub("-", cleaned).strip("-")
    return slug or "unknown"


def resolve_model_pricing(
    model_name: str, pricing_table: Mapping[str, ModelPricing]
) -> ModelPricing | None:
    """Find an explicit override by exact model ID or configured family."""
    model = normalize_model_name(model_name)
    family = _infer_family_key(model)
    return pricing_table.get(model) or (pricing_table.get(family) if family else None)


def _infer_family_key(model: str) -> str | None:
    """Map an arbitrary model slug to a `family:*` fallback key."""
    if "claude" in model and "opus" in model:
        return "family:claude-opus"
    if "claude" in model and ("sonnet" in model or "haiku" in model):
        return "family:claude-sonnet"
    if "grok" in model:
        return _infer_grok_family(model)
    if model.startswith("gemini-4"):
        return "family:gemini-4"
    if "gemini" in model and "flash" in model:
        return "family:gemini-flash"
    if "gemini" in model:
        return "family:gemini-pro"
    return None


def _infer_grok_family(model: str) -> str:
    """Map a Grok model slug to `family:grok`, `family:grok-fast`, or `family:grok-mini`."""
    if "mini" in model:
        return "family:grok-mini"
    if "fast" in model and "code" not in model:
        return "family:grok-fast"
    return "family:grok"


def has_custom_model_pricing(
    model_name: str,
    pricing_table: Mapping[str, ModelPricing],
) -> bool:
    """Return `True` when `pricing_table` overrides the default rate for `model_name`."""
    return normalize_model_name(model_name) != "unknown" and (
        resolve_model_pricing(model_name, pricing_table) is not None
    )


def estimate_text_tokens(text: str) -> int:
    """Estimate subword BPE token count deterministically when provider usage is omitted."""
    if not text or not text.strip():
        return 0
    piece_estimate = 0
    for match in _TOKEN_PIECE_RE.finditer(text):
        piece = match.group(0)
        piece_estimate += max(1, math.ceil(len(piece) / _CHARS_PER_SUBWORD))
    byte_estimate = math.ceil(len(text.encode("utf-8")) / _BYTES_PER_TOKEN)
    return max(1, max(piece_estimate, byte_estimate))


def calculate_turn_cost(
    *,
    model: str,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    pricing_table: Mapping[str, ModelPricing],
) -> float:
    """Estimate the turn cost with the bundled catalog and local rate overrides."""
    uncached, cached, output = (
        max(input_tokens, 0),
        max(cached_input_tokens, 0),
        max(output_tokens, 0),
    )
    usage = Usage(input_tokens=uncached + cached, cache_read_tokens=cached, output_tokens=output)
    model = normalize_model_name(model)
    override = resolve_model_pricing(model, pricing_table)
    if override is not None and all(
        rate is not None
        for rate in (
            override.input_per_million,
            override.cached_input_per_million,
            override.output_per_million,
        )
    ):
        return _apply_override(usage, override, None)
    try:
        quoted = calc_price(usage, _catalog_model(model))
    except LookupError:
        override = override or pricing_table.get("unknown")
        return _apply_override(usage, override, None) if override else math.nan
    if override is None:
        return float(quoted.total_price)
    return _apply_override(usage, override, quoted.model_price)


def _catalog_model(model: str) -> str:
    """Map known reasoning-effort suffixes to the same API model."""
    base, _, suffix = model.rpartition("-")
    if base in ("gemini-4-argon", "claude-opus-5-5", "claude-sonnet-5-5") and suffix in (
        "low",
        "medium",
        "high",
    ):
        return base
    return model


def _apply_override(usage: Usage, override: ModelPricing, base: ModelPrice | None) -> float:
    prices = dict(vars(base)) if base is not None else {}
    units = (
        (
            "input_mtok",
            int(usage.input_tokens) - int(usage.cache_read_tokens),
            override.input_per_million,
        ),
        ("cache_read_mtok", usage.cache_read_tokens, override.cached_input_per_million),
        ("output_mtok", usage.output_tokens, override.output_per_million),
    )
    for key, count, rate in units:
        if rate is not None:
            prices[key] = Decimal(str(rate))
        elif count and base is None:
            return math.nan
    return float(ModelPrice(**prices).calc_price(usage)["total_price"])
