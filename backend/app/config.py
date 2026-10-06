"""Runtime configuration. Every secret comes from the environment (backend/.env)."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env")
ARTIFACTS_DIR = Path(os.getenv("NQ_ARTIFACTS_DIR") or ROOT_DIR / "ml" / "artifacts")

# The one authoritative mapping: model output index -> class. Training writes the same order to
# ml/artifacts/labels.json and the classifier refuses to load if the two ever differ.
CLASSES = ["glioma", "meningioma", "pituitary", "no_tumor"]
TUMOR_CLASSES = ["glioma", "meningioma", "pituitary"]
CLASS_LABELS = {"glioma": "Glioma", "meningioma": "Meningioma", "pituitary": "Pituitary Tumor", "no_tumor": "No Tumor"}

# Used only when ml/artifacts/thresholds.json is missing (mock mode / tests).
# Real values are tuned on the validation split by `python -m ml.train`.
DEFAULT_THRESHOLDS = {
    "min_conf": 0.85, "min_margin": 0.15, "routine_conf": 0.90, "temperature": 1.0,
    "max_wait_min": 60, "ood_energy_min": None, "tuned_on": "defaults (no trained artifacts found)",
}


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


class Settings:
    def __init__(self) -> None:
        self.mock_mode = _bool("NQ_MOCK_MODE")  # no network: mock classifier + template report writer + local store
        self.secret_key = os.getenv("SECRET_KEY", "dev-only-change-me")
        self.token_hours = int(os.getenv("TOKEN_HOURS", "12"))
        self.cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if o.strip()]
        self.data_dir = Path(os.getenv("NQ_DATA_DIR", str(BACKEND_DIR / "data")))

        self.supabase_url = os.getenv("SUPABASE_URL", "").rstrip("/")
        self.supabase_anon_key = os.getenv("SUPABASE_ANON_KEY", "")
        self.supabase_service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        self.supabase_service_email = os.getenv("SUPABASE_SERVICE_EMAIL", "")
        self.supabase_service_password = os.getenv("SUPABASE_SERVICE_PASSWORD", "")
        self.supabase_bucket = os.getenv("SUPABASE_BUCKET", "scans")

        self.dashscope_key = os.getenv("DASHSCOPE_API_KEY", "")
        self.dashscope_base = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1").rstrip("/")
        self.qwen_text_model = os.getenv("QWEN_TEXT_MODEL", "qwen3.8-flash")
        self.qwen_report_model = os.getenv("QWEN_REPORT_MODEL", "qwen3.8-max")
        self.assemblyai_key = os.getenv("ASSEMBLYAI_API_KEY", "")

        self.admin_email = os.getenv("ADMIN_EMAIL", "")
        self.admin_password = os.getenv("ADMIN_PASSWORD", "")
        self.admin_invite_code = os.getenv("ADMIN_INVITE_CODE", "")
        # sessions / browser security
        self.app_url = os.getenv("APP_URL", "http://localhost:3000").rstrip("/")
        self.trust_proxy = _bool("TRUST_PROXY")                          # true when the site proxies /api to this server
        self.cookie_secure = _bool("COOKIE_SECURE")                      # true in production (HTTPS)
        self.cookie_samesite = os.getenv("COOKIE_SAMESITE", "lax").lower()  # "none" only if API and site are on different sites
        # outgoing email (verification, password reset). Empty -> development outbox
        self.smtp_host = os.getenv("SMTP_HOST", "")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER", "")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "")
        self.smtp_from = os.getenv("SMTP_FROM", "")
        # Hosts that block outgoing SMTP (Railway): hand the message to the site's /mail-relay over HTTPS instead.
        self.mail_relay_url = os.getenv("MAIL_RELAY_URL", "")
        self.mail_relay_secret = os.getenv("MAIL_RELAY_SECRET", "")
        self.google_client_id = os.getenv("GOOGLE_CLIENT_ID", "")
        self.support_email = os.getenv("SUPPORT_EMAIL", "2200031362csehh@gmail.com")
        self.support_phone = os.getenv("SUPPORT_PHONE", "+971 528813637")

    @property
    def use_supabase(self) -> bool:
        has_identity = bool(self.supabase_service_key or (self.supabase_service_email and self.supabase_service_password))
        return bool(not self.mock_mode and self.supabase_url and self.supabase_anon_key and has_identity)

    @property
    def use_qwen(self) -> bool:
        return bool(not self.mock_mode and self.dashscope_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_thresholds() -> dict:
    path = ARTIFACTS_DIR / "thresholds.json"
    if path.exists():
        return {**DEFAULT_THRESHOLDS, **json.loads(path.read_text())}
    return dict(DEFAULT_THRESHOLDS)


def load_json_artifact(name: str):
    path = ARTIFACTS_DIR / name
    return json.loads(path.read_text()) if path.exists() else None
