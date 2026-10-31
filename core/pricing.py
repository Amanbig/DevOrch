"""Cost estimates for model usage.

Prices are USD per 1M tokens and are **approximate defaults** that go stale; override or add models
under ``pricing:`` in ``~/.devorch/config.yaml``::

    pricing:
      claude-sonnet-4:           # matched as a prefix of the model id
        input: 3.0
        output: 15.0
        cache_read: 0.30         # optional; defaults to the input price
        cache_write: 3.75        # optional; defaults to the input price

Models with no known price are never guessed: their tokens are counted but they contribute no cost,
and the totals say so. Local providers (Ollama, LM Studio) are free.
"""

from dataclasses import dataclass, field
from typing import Any

from schemas.message import TokenUsage


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_read: float | None = None  # None -> same as input
    cache_write: float | None = None  # None -> same as input


# Approximate list prices (USD / 1M tokens). Keys are matched as lowercase prefixes, longest first.
DEFAULT_PRICES: dict[str, Price] = {
    "gpt-4o-mini": Price(0.15, 0.60, cache_read=0.075),
    "gpt-4o": Price(2.50, 10.00, cache_read=1.25),
    "claude-opus-4": Price(15.0, 75.0, cache_read=1.50, cache_write=18.75),
    "claude-sonnet-4": Price(3.0, 15.0, cache_read=0.30, cache_write=3.75),
    "claude-3-5-sonnet": Price(3.0, 15.0, cache_read=0.30, cache_write=3.75),
    "claude-3-5-haiku": Price(0.80, 4.0, cache_read=0.08, cache_write=1.0),
    "claude-3-opus": Price(15.0, 75.0, cache_read=1.50, cache_write=18.75),
    "claude-3-haiku": Price(0.25, 1.25, cache_read=0.03, cache_write=0.30),
    "deepseek-chat": Price(0.27, 1.10, cache_read=0.07),
    "gemini-2.0-flash": Price(0.10, 0.40),
    "gemini-1.5-pro": Price(1.25, 5.00),
}

FREE_PROVIDERS = {"local", "lmstudio"}


def _normalize(model: str) -> str:
    """Lowercase and drop a router prefix like ``anthropic/`` (OpenRouter style ids)."""
    return model.lower().rsplit("/", 1)[-1]


def parse_overrides(raw: Any) -> dict[str, Price]:
    """Read the ``pricing:`` mapping from config, ignoring malformed entries."""
    out: dict[str, Price] = {}
    if not isinstance(raw, dict):
        return out
    for model, cfg in raw.items():
        if not isinstance(cfg, dict):
            continue
        try:
            out[_normalize(str(model))] = Price(
                input=float(cfg["input"]),
                output=float(cfg["output"]),
                cache_read=float(cfg["cache_read"]) if "cache_read" in cfg else None,
                cache_write=float(cfg["cache_write"]) if "cache_write" in cfg else None,
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


class PriceBook:
    def __init__(self, overrides: dict[str, Price] | None = None):
        self.overrides = overrides or {}

    @staticmethod
    def _longest_prefix(table: dict[str, Price], model: str) -> Price | None:
        for key in sorted(table, key=len, reverse=True):
            if model.startswith(key):
                return table[key]
        return None

    def lookup(self, provider: str, model: str) -> Price | None:
        if provider in FREE_PROVIDERS:
            return Price(0.0, 0.0)
        name = _normalize(model)
        return self._longest_prefix(self.overrides, name) or self._longest_prefix(
            DEFAULT_PRICES, name
        )


def usage_cost(usage: TokenUsage, price: Price) -> float:
    """USD cost of one call. ``prompt_tokens`` includes cached tokens (provider-normalized)."""
    cached = min(usage.cached_tokens, usage.prompt_tokens)
    written = min(usage.cache_write_tokens, max(0, usage.prompt_tokens - cached))
    fresh = usage.prompt_tokens - cached - written
    read_price = price.cache_read if price.cache_read is not None else price.input
    write_price = price.cache_write if price.cache_write is not None else price.input
    return (
        fresh * price.input
        + cached * read_price
        + written * write_price
        + usage.completion_tokens * price.output
    ) / 1_000_000


@dataclass
class ModelCost:
    prompt_tokens: int = 0
    cached_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    priced: bool = True


@dataclass
class CostTracker:
    """Accumulates cost per call, at the price of the model that served each call."""

    prices: PriceBook = field(default_factory=PriceBook)
    by_model: dict[str, ModelCost] = field(default_factory=dict)

    def add(self, provider: str, model: str, usage: TokenUsage | None) -> float | None:
        """Record one call; returns its cost, or None if the model has no known price."""
        if usage is None:
            return None
        entry = self.by_model.setdefault(f"{provider}/{model}", ModelCost())
        entry.prompt_tokens += usage.prompt_tokens
        entry.cached_tokens += usage.cached_tokens
        entry.completion_tokens += usage.completion_tokens
        price = self.prices.lookup(provider, model)
        if price is None:
            entry.priced = False
            return None
        cost = usage_cost(usage, price)
        entry.cost += cost
        return cost

    @property
    def total(self) -> float:
        return sum(m.cost for m in self.by_model.values())

    @property
    def has_unpriced(self) -> bool:
        return any(not m.priced for m in self.by_model.values())

    @property
    def has_priced(self) -> bool:
        return any(m.priced for m in self.by_model.values())


def format_cost(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value == 0:
        return "$0.00"
    if value < 0.01:
        return f"${value:.4f}"
    return f"${value:,.2f}"
