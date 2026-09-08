"""Settings and setup API routes."""

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.paths import CONFIG_DIR, RESUME_DIR
from src.settings import Settings, load_settings, save_settings

router = APIRouter(tags=["settings"])


# ---------- helpers ----------

def _mask(value: str) -> str:
    """Mask a secret, showing only the last 4 characters."""
    if not value or len(value) <= 4:
        return "*" * len(value) if value else ""
    return "*" * (len(value) - 4) + value[-4:]


def _settings_to_response(s: Settings) -> dict:
    """Return settings with sensitive fields masked."""
    return {
        # Generic AI provider fields
        "ai_provider": s.effective_provider,
        "ai_api_key": _mask(s.effective_api_key),
        "ai_model": s.effective_model,
        "has_ai_key": bool(s.effective_provider == "ollama" or (s.effective_api_key and "xxxx" not in s.effective_api_key)),
        # Legacy Anthropic fields (for backward compat)
        "anthropic_api_key": _mask(s.anthropic_api_key),
        "anthropic_model": s.anthropic_model,
        "has_anthropic_key": bool(s.anthropic_api_key and not s.anthropic_api_key.startswith("sk-ant-xxxx")),
        # Other
        "notion_token": _mask(s.notion_token),
        "notion_db_id": s.notion_db_id,
        "has_notion_token": bool(s.notion_token and s.notion_token != "secret_xxxx"),
    }


# ---------- settings CRUD ----------

@router.get("/settings")
def get_settings():
    return _settings_to_response(load_settings())


class SettingsUpdate(BaseModel):
    ai_provider: str | None = None
    ai_api_key: str | None = None
    ai_model: str | None = None
    anthropic_api_key: str | None = None
    anthropic_model: str | None = None
    notion_token: str | None = None
    notion_db_id: str | None = None


@router.put("/settings")
def update_settings(body: SettingsUpdate):
    from src.ai.ai_client import reset_provider

    current = load_settings()
    updates = body.model_dump(exclude_none=True)
    # Don't overwrite real keys with masked values
    for key in ("ai_api_key", "anthropic_api_key", "notion_token"):
        if key in updates and updates[key].startswith("*"):
            del updates[key]
    merged = current.model_copy(update=updates)
    save_settings(merged)
    reset_provider()  # Clear cached provider so new settings take effect
    return _settings_to_response(merged)


# ---------- key validation ----------

class ValidateKeyRequest(BaseModel):
    key: str
    provider: str = "anthropic"


@router.post("/settings/validate-key")
def validate_api_key(body: ValidateKeyRequest):
    """Test an AI provider API key with a minimal request."""
    if body.provider == "ollama":
        # Ollama has no key — just check if it's running
        import httpx
        try:
            resp = httpx.get("http://localhost:11434/api/tags", timeout=5)
            resp.raise_for_status()
            return {"valid": True}
        except Exception:
            return {"valid": False, "error": "Cannot connect to Ollama — is it running? (ollama serve)"}

    if not body.key or "xxxx" in body.key:
        raise HTTPException(status_code=400, detail="Please enter a real API key")

    if body.provider == "gemini":
        try:
            import google.generativeai as genai
            genai.configure(api_key=body.key)
            model = genai.GenerativeModel(model_name="gemini-3.6-flash")
            model.generate_content("hi", generation_config=genai.types.GenerationConfig(max_output_tokens=10))
            return {"valid": True}
        except Exception as e:
            err_str = str(e).lower()
            if "api key" in err_str or "permission" in err_str or "invalid" in err_str:
                return {"valid": False, "error": "Invalid API key"}
            return {"valid": False, "error": str(e)}

    # Default: Anthropic
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=body.key)
        client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1,
            messages=[{"role": "user", "content": "hi"}],
        )
        return {"valid": True}
    except Exception as e:
        err_str = str(e).lower()
        if "auth" in err_str:
            return {"valid": False, "error": "Invalid API key"}
        if "rate" in err_str:
            return {"valid": False, "error": "Rate limited — key may be valid, try again shortly"}
        if "connect" in err_str:
            return {"valid": False, "error": "Cannot reach Anthropic API — check your network"}
        return {"valid": False, "error": str(e)}


# ---------- setup status ----------

@router.get("/setup/status")
def get_setup_status():
    """Check which setup steps are complete."""
    settings = load_settings()

    # AI provider configured
    has_provider = bool(settings.effective_provider)
    has_key = False
    if settings.effective_provider == "ollama":
        has_key = True  # No key needed
    elif settings.effective_api_key and "xxxx" not in settings.effective_api_key:
        has_key = True

    # Resume
    master_path = RESUME_DIR / "master.json"
    has_resume = False
    if master_path.exists():
        try:
            data = json.loads(master_path.read_text())
            has_resume = bool(data.get("experience"))
        except (json.JSONDecodeError, KeyError):
            pass

    # Preferences
    prefs_path = CONFIG_DIR / "preferences.yaml"
    has_preferences = prefs_path.exists()

    is_complete = has_provider and has_key and has_resume and has_preferences

    return {
        "is_complete": is_complete,
        "steps": {
            "ai_provider": has_provider and has_key,
            "api_key": has_key,  # Legacy field name kept for UI compat
            "resume": has_resume,
            "preferences": has_preferences,
        },
    }
