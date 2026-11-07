"""Context-window and output limits per model.

DevOrch used one fixed budget for every model (compact history at 16k tokens), which wastes the 128k-1M
windows of current models and throws away older tool output far too early. The values below are
**approximate** published limits matched as lowercase prefixes (longest first), and go stale; add or override
models under ``context_windows:`` in ``~/.devorch/config.yaml`` (tokens)::

    context_windows:
      my-fine-tune: 32000

An unknown model keeps the old conservative budget. Local servers (Ollama, LM Studio) enforce their own
context size regardless of what the model supports, so they are treated as unknown too.
"""

from typing import Any

DEFAULT_COMPACT_THRESHOLD = 16_000  # what DevOrch used for every model
DEFAULT_MAX_CONTEXT = 24_000
COMPACT_FRACTION = 0.6  # compact history at this share of the window...
COMPACT_CAP = (
    64_000  # ...but never later than this: every call re-sends the history, so it costs money
)
MIN_COMPACT_THRESHOLD = 3_000

# Approximate context windows in tokens, matched as prefixes of the lowercased model id.
CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-4.1": 1_000_000,
    "gpt-4o": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4-32k": 32_768,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
    "o1": 200_000,
    "o3": 200_000,
    "o4": 200_000,
    "claude-": 200_000,
    "gemini-1.5": 1_000_000,
    "gemini-2": 1_000_000,
    "deepseek-": 64_000,
    "mistral-large": 128_000,
    "ministral": 128_000,
    "pixtral": 128_000,
    "codestral": 32_000,
    "moonshot-v1-8k": 8_192,
    "moonshot-v1-32k": 32_768,
    "moonshot-v1-128k": 131_072,
    "llama-3.1": 128_000,
    "llama-3.3": 128_000,
    "llama3.1": 128_000,
    "llama3.3": 128_000,
}

# Providers whose context size is set by a local server, not by the model.
SERVER_CONTROLLED = {"local", "lmstudio", "custom"}

# Maximum output tokens for Anthropic models (prefix match). Asking for more than a model allows is a
# 400 error, so unknown models get a conservative default.
ANTHROPIC_MAX_OUTPUT: dict[str, int] = {
    "claude-opus-4": 32_000,
    "claude-sonnet-4": 64_000,
    "claude-3-7": 64_000,
    "claude-3-5": 8_192,
    "claude-3": 4_096,
}
ANTHROPIC_DEFAULT_OUTPUT = 8_192
# The SDK refuses non-streaming requests that could take >10 minutes (about 21k tokens), so cap those.
NON_STREAMING_OUTPUT_CAP = 16_000


def _normalize(model: str) -> str:
    """Lowercase and drop a router prefix like ``anthropic/`` (OpenRouter style ids)."""
    return model.lower().rsplit("/", 1)[-1]


def _longest_prefix(table: dict[str, int], model: str) -> int | None:
    for key in sorted(table, key=len, reverse=True):
        if model.startswith(key):
            return table[key]
    return None


def parse_overrides(raw: Any) -> dict[str, int]:
    """Read the ``context_windows:`` mapping from config, ignoring malformed entries."""
    out: dict[str, int] = {}
    if not isinstance(raw, dict):
        return out
    for model, tokens in raw.items():
        try:
            value = int(tokens)
        except (TypeError, ValueError):
            continue
        if value > 0:
            out[_normalize(str(model))] = value
    return out


class ModelLimits:
    def __init__(self, overrides: dict[str, int] | None = None):
        self.overrides = overrides or {}

    def context_window(self, provider: str, model: str) -> int | None:
        """The model's context window in tokens, or None if unknown."""
        name = _normalize(model)
        override = _longest_prefix(self.overrides, name)
        if override is not None:
            return override  # an explicit override wins even for server-controlled providers
        if provider in SERVER_CONTROLLED:
            return None
        return _longest_prefix(CONTEXT_WINDOWS, name)

    def compact_threshold(self, provider: str, model: str) -> int:
        """History size (tokens) at which older tool output starts being compacted."""
        window = self.context_window(provider, model)
        if window is None:
            return DEFAULT_COMPACT_THRESHOLD
        return max(MIN_COMPACT_THRESHOLD, min(int(window * COMPACT_FRACTION), COMPACT_CAP))


def anthropic_max_output(model: str, streaming: bool) -> int:
    """``max_tokens`` to request from an Anthropic model."""
    limit = _longest_prefix(ANTHROPIC_MAX_OUTPUT, _normalize(model)) or ANTHROPIC_DEFAULT_OUTPUT
    return limit if streaming else min(limit, NON_STREAMING_OUTPUT_CAP)
