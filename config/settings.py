import copy
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

from config.project_settings import ProjectSettings, load_project_settings

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
    mcp_servers: dict[str, dict] = field(default_factory=dict)
    pricing: dict[str, dict] = field(
        default_factory=dict
    )  # raw `pricing:` overrides (see core/pricing)
    # Set when per-project settings were applied (see config/project_settings.py)
    project_notices: list[str] = field(default_factory=list)
    project_default_mode: str | None = None
    # key -> (global value, value applied from the project); used to keep project values
    # out of ~/.devorch/config.yaml when settings are saved.
    _project_applied: dict = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, include_project: bool = True) -> "Settings":
        """Load settings from config file, keyring, and env vars (+ project settings)."""
        settings = cls()

        # Load from YAML if exists and yaml is available
        if YAML_AVAILABLE and CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f:
                    data = yaml.safe_load(f) or {}
                settings.default_provider = data.get("default_provider", "openai")
                for name, config in data.get("providers", {}).items():
                    settings.providers[name] = ProviderConfig(**config)
                settings.mcp_servers = data.get("mcp_servers", {})
                if isinstance(data.get("pricing"), dict):
                    settings.pricing = data["pricing"]
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

        if include_project:
            settings._apply_project(load_project_settings())

        return settings

    def _apply_project(self, ps: ProjectSettings | None) -> None:
        if ps is None:
            return
        self.project_notices = list(ps.notices)
        self.project_default_mode = ps.effective_mode()

        if ps.default_provider:
            self._project_applied["default_provider"] = (
                self.default_provider,
                ps.default_provider,
            )
            self.default_provider = ps.default_provider
        for name, model in ps.models.items():
            cfg = self.providers.setdefault(name, ProviderConfig())
            self._project_applied[("model", name)] = (cfg.default_model, model)
            cfg.default_model = model
        if ps.trusted and ps.mcp_servers:
            merged = {**self.mcp_servers, **ps.mcp_servers}
            self._project_applied["mcp_servers"] = (self.mcp_servers, merged)
            self.mcp_servers = merged

    def global_view(self) -> "Settings":
        """Copy with project-applied values reverted, unless the user changed them since."""
        view = copy.deepcopy(self)
        for key, (original, applied) in self._project_applied.items():
            if key == "default_provider":
                if view.default_provider == applied:
                    view.default_provider = original
            elif key == "mcp_servers":
                if view.mcp_servers == applied:
                    view.mcp_servers = original
            else:
                _, name = key
                if name in view.providers and view.providers[name].default_model == applied:
                    view.providers[name].default_model = original
        return view

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
    settings = settings.global_view()

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

    # Include MCP server config
    if settings.mcp_servers:
        data["mcp_servers"] = settings.mcp_servers

    # Keep user-defined price overrides (otherwise saving would silently drop them)
    if settings.pricing:
        data["pricing"] = settings.pricing

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
