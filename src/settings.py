"""Settings module — manages API keys and service configuration.

Reads from config/settings.yaml with fallback to .env for backward compatibility.
Sensitive fields (API keys, tokens) are encrypted at rest using Fernet.
"""

import os
import threading

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from src.crypto import decrypt_value, encrypt_value
from src.paths import CONFIG_DIR, PROJECT_ROOT

# Fields that contain secrets and should be encrypted on disk
_SENSITIVE_FIELDS = {"ai_api_key", "anthropic_api_key", "notion_token"}

# Load .env as fallback source
load_dotenv(PROJECT_ROOT / ".env", override=False)

SETTINGS_PATH = CONFIG_DIR / "settings.yaml"
_lock = threading.Lock()


class Settings(BaseModel):
    # Generic AI provider fields
    ai_provider: str = Field(default="")   # "anthropic", "gemini", "ollama"
    ai_api_key: str = Field(default="")    # Provider-specific API key
    ai_model: str = Field(default="")      # Provider-specific model name

    # Legacy Anthropic fields (kept for backward compatibility)
    anthropic_api_key: str = Field(default="")
    anthropic_model: str = Field(default="claude-haiku-4-5-20251001")

    # Other services
    notion_token: str = Field(default="")
    notion_db_id: str = Field(default="")

    @property
    def effective_provider(self) -> str:
        """Resolve which AI provider to use, with backward compat."""
        if self.ai_provider:
            return self.ai_provider
        # Legacy fallback: if anthropic_api_key is set, assume anthropic
        if self.anthropic_api_key and not self.anthropic_api_key.startswith("sk-ant-xxxx"):
            return "anthropic"
        return ""

    @property
    def effective_api_key(self) -> str:
        """Resolve the API key for the active provider."""
        if self.ai_api_key:
            return self.ai_api_key
        if self.effective_provider == "anthropic":
            return self.anthropic_api_key
        return ""

    @property
    def effective_model(self) -> str:
        """Resolve the model name for the active provider."""
        if self.ai_model:
            return self.ai_model
        provider = self.effective_provider
        if provider == "anthropic":
            return self.anthropic_model or "claude-haiku-4-5-20251001"
        if provider == "gemini":
            return "gemini-3.6-flash"
        if provider == "ollama":
            return "llama3.2"
        return ""


def load_settings() -> Settings:
    """Load settings from YAML, falling back to environment variables."""
    data: dict = {}

    # Primary source: settings.yaml
    if SETTINGS_PATH.exists():
        try:
            raw = yaml.safe_load(SETTINGS_PATH.read_text())
            if isinstance(raw, dict):
                data = raw
        except Exception:
            pass

    # Fallback: environment variables (from .env or system)
    env_map = {
        "ai_provider": "AI_PROVIDER",
        "ai_api_key": "AI_API_KEY",
        "ai_model": "AI_MODEL",
        "anthropic_api_key": "ANTHROPIC_API_KEY",
        "anthropic_model": "ANTHROPIC_MODEL",
        "notion_token": "NOTION_TOKEN",
        "notion_db_id": "NOTION_JOBS_DB_ID",
    }
    for field, env_var in env_map.items():
        if not data.get(field):
            env_val = os.getenv(env_var)
            if env_val:
                data[field] = env_val

    # Decrypt sensitive fields loaded from settings.yaml
    for field in _SENSITIVE_FIELDS:
        if field in data and isinstance(data[field], str):
            data[field] = decrypt_value(data[field])

    return Settings(**{k: v for k, v in data.items() if k in Settings.model_fields})


def save_settings(settings: Settings) -> None:
    """Atomically write settings to YAML with sensitive fields encrypted."""
    with _lock:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = settings.model_dump()

        # Encrypt sensitive fields before writing to disk
        for field in _SENSITIVE_FIELDS:
            if field in data and data[field]:
                data[field] = encrypt_value(data[field])

        tmp_path = SETTINGS_PATH.with_suffix(".yaml.tmp")
        tmp_path.write_text(
            yaml.dump(data, default_flow_style=False, sort_keys=False)
        )
        os.replace(str(tmp_path), str(SETTINGS_PATH))
