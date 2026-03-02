import os
from pathlib import Path
from typing import Optional, Dict
from dataclasses import dataclass, field

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

CONFIG_DIR = Path.home() / ".devpilot"
CONFIG_FILE = CONFIG_DIR / "config.yaml"


@dataclass
class ProviderConfig:
    api_key: Optional[str] = None
    default_model: str = ""
    base_url: Optional[str] = None


@dataclass
class Settings:
    default_provider: str = "openai"
    providers: Dict[str, ProviderConfig] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Settings":
        """Load settings from config file, falling back to env vars."""
        settings = cls()

        # Load from YAML if exists and yaml is available
        if YAML_AVAILABLE and CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = yaml.safe_load(f) or {}
                settings.default_provider = data.get("default_provider", "openai")
                for name, config in data.get("providers", {}).items():
                    settings.providers[name] = ProviderConfig(**config)
            except Exception:
                pass  # Fall back to defaults if config is invalid

        # Environment variable mappings: (env_var_name, default_model)
        env_mappings = {
            "openai": ("OPENAI_API_KEY", "gpt-4o"),
            "anthropic": ("ANTHROPIC_API_KEY", "claude-sonnet-4-20250514"),
            "gemini": ("GOOGLE_API_KEY", "gemini-1.5-pro"),
            "local": (None, "llama3"),
        }

        for provider, (env_var, default_model) in env_mappings.items():
            if provider not in settings.providers:
                settings.providers[provider] = ProviderConfig(default_model=default_model)

            # Set default model if not configured
            if not settings.providers[provider].default_model:
                settings.providers[provider].default_model = default_model

            # Override with environment variable if present
            if env_var and os.environ.get(env_var):
                settings.providers[provider].api_key = os.environ[env_var]

        # Set default base_url for local provider
        if "local" in settings.providers and not settings.providers["local"].base_url:
            settings.providers["local"].base_url = "http://localhost:11434/v1"

        return settings

    def get_api_key(self, provider: str) -> Optional[str]:
        """Get API key for a provider."""
        config = self.providers.get(provider)
        return config.api_key if config else None

    def get_default_model(self, provider: str) -> str:
        """Get default model for a provider."""
        config = self.providers.get(provider)
        return config.default_model if config else ""

    def get_base_url(self, provider: str) -> Optional[str]:
        """Get base URL for a provider (used for local/custom endpoints)."""
        config = self.providers.get(provider)
        return config.base_url if config else None


def ensure_config_dir():
    """Create config directory if it doesn't exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def save_config(settings: Settings):
    """Save settings to config file."""
    if not YAML_AVAILABLE:
        raise RuntimeError("PyYAML is required to save config. Install with: pip install pyyaml")

    ensure_config_dir()

    data = {
        "default_provider": settings.default_provider,
        "providers": {}
    }

    for name, config in settings.providers.items():
        provider_data = {}
        if config.api_key:
            provider_data["api_key"] = config.api_key
        if config.default_model:
            provider_data["default_model"] = config.default_model
        if config.base_url:
            provider_data["base_url"] = config.base_url
        if provider_data:
            data["providers"][name] = provider_data

    with open(CONFIG_FILE, "w") as f:
        yaml.safe_dump(data, f, default_flow_style=False)
