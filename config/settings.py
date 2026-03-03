import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml

    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

try:
    import keyring

    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False

CONFIG_DIR = Path.home() / ".devorch"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
KEYRING_SERVICE = "devorch"


@dataclass
class ProviderConfig:
    api_key: str | None = None
    default_model: str = ""
    base_url: str | None = None
    key_encrypted: bool = False  # True if key is stored in keyring


@dataclass
class Settings:
    default_provider: str = "openai"
    providers: dict[str, ProviderConfig] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Settings":
        """Load settings from config file, keyring, and env vars."""
        settings = cls()

        # Load from YAML if exists and yaml is available
        if YAML_AVAILABLE and CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f:
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
            "groq": ("GROQ_API_KEY", "llama-3.1-70b-versatile"),
            "openrouter": ("OPENROUTER_API_KEY", "openai/gpt-4o"),
            "mistral": ("MISTRAL_API_KEY", "mistral-large-latest"),
            "together": ("TOGETHER_API_KEY", "meta-llama/Llama-3-70b-chat-hf"),
            "lmstudio": (None, ""),
            "github_copilot": ("GITHUB_TOKEN", "gpt-4o"),
            "deepseek": ("DEEPSEEK_API_KEY", "deepseek-chat"),
            "kimi": ("MOONSHOT_API_KEY", "moonshot-v1-32k"),
            "custom": ("CUSTOM_API_KEY", ""),
        }

        for provider, (env_var, default_model) in env_mappings.items():
            if provider not in settings.providers:
                settings.providers[provider] = ProviderConfig(default_model=default_model)

            # Set default model if not configured
            if not settings.providers[provider].default_model:
                settings.providers[provider].default_model = default_model

            # Priority: 1. Keyring, 2. Env var, 3. Config file
            # Try keyring first (encrypted storage)
            if KEYRING_AVAILABLE and not settings.providers[provider].api_key:
                try:
                    key = keyring.get_password(KEYRING_SERVICE, provider)
                    if key:
                        settings.providers[provider].api_key = key
                        settings.providers[provider].key_encrypted = True
                except Exception:
                    pass  # Keyring not available or failed

            # Override with environment variable if present
            if env_var and os.environ.get(env_var):
                settings.providers[provider].api_key = os.environ[env_var]
                settings.providers[provider].key_encrypted = False

        # Set default base_url for local provider
        if "local" in settings.providers and not settings.providers["local"].base_url:
            settings.providers["local"].base_url = "http://localhost:11434/v1"

        return settings

    def get_api_key(self, provider: str) -> str | None:
        """Get API key for a provider."""
        config = self.providers.get(provider)
        return config.api_key if config else None

    def get_default_model(self, provider: str) -> str:
        """Get default model for a provider."""
        config = self.providers.get(provider)
        return config.default_model if config else ""

    def get_base_url(self, provider: str) -> str | None:
        """Get base URL for a provider (used for local/custom endpoints)."""
        config = self.providers.get(provider)
        return config.base_url if config else None

    def is_key_encrypted(self, provider: str) -> bool:
        """Check if the API key is stored encrypted."""
        config = self.providers.get(provider)
        return config.key_encrypted if config else False


def ensure_config_dir():
    """Create config directory if it doesn't exist."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def set_api_key(provider: str, api_key: str) -> bool:
    """
    Store an API key securely using keyring.
    Returns True if stored encrypted, False if keyring unavailable.
    """
    if not KEYRING_AVAILABLE:
        return False

    try:
        keyring.set_password(KEYRING_SERVICE, provider, api_key)
        return True
    except Exception:
        return False


def delete_api_key(provider: str) -> bool:
    """Delete an API key from keyring."""
    if not KEYRING_AVAILABLE:
        return False

    try:
        keyring.delete_password(KEYRING_SERVICE, provider)
        return True
    except Exception:
        return False


def save_config(settings: Settings):
    """Save settings to config file (excluding API keys - those go in keyring)."""
    if not YAML_AVAILABLE:
        raise RuntimeError("PyYAML is required to save config. Install with: pip install pyyaml")

    ensure_config_dir()

    data = {"default_provider": settings.default_provider, "providers": {}}

    for name, config in settings.providers.items():
        provider_data = {}
        # Don't save API keys to file - they should be in keyring or env vars
        if config.default_model:
            provider_data["default_model"] = config.default_model
        if config.base_url:
            provider_data["base_url"] = config.base_url
        if provider_data:
            data["providers"][name] = provider_data

    with open(CONFIG_FILE, "w") as f:
        yaml.safe_dump(data, f, default_flow_style=False)


def keyring_available() -> bool:
    """Check if keyring is available and working."""
    if not KEYRING_AVAILABLE:
        return False
    try:
        # Try a test operation
        keyring.get_password(KEYRING_SERVICE, "__test__")
        return True
    except Exception:
        return False
