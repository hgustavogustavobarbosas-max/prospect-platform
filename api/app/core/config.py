from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULTS = {"change-me", "change-me-service-key"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    database_url: str = "postgresql+psycopg://prospect:prospect@localhost:5432/prospect"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60
    service_api_key: str = "change-me-service-key"
    admin_email: str | None = None
    admin_password: str | None = None
    log_level: str = "INFO"
    log_json: bool = True

    # --- Prospeccao (Parte 2) ---
    google_places_api_key: str | None = None
    places_daily_call_limit: int = 50
    places_cost_micro_usd_per_call: int = 0  # preencha com o preco vigente do seu SKU
    # strict: persiste so place_id + analise propria. permissive: persiste campos do Places
    # (use apenas se voce confirmou que seu caso de uso e permitido pelos termos do Google).
    places_storage_mode: Literal["strict", "permissive"] = "strict"
    places_cache_ttl_days: int = 30
    site_check_enabled: bool = True
    site_check_timeout: float = 5.0
    pilot_segments: str = "barbearia,estetica"
    tier_a_min: int = 70
    tier_b_min: int = 40

    # --- IA no scoring (opcional) ---
    llm_enabled: bool = False
    llm_provider: Literal["anthropic", "gemini"] = "anthropic"
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    llm_model: str = "claude-haiku-5-5"
    llm_daily_token_limit: int = 200_000
    llm_daily_call_limit: int = 250
    llm_rpm_limit: int = 10
    llm_input_tpm_limit: int = 2_500
    llm_min_base_score: int = 30
    llm_cost_micro_usd_per_1k_tokens: int = 0  # preco do seu modelo (1e-6 USD) p/ acompanhar custo

    # --- Agente comercial (Parte 3) ---
    agent_enabled: bool = True
    agent_model: str = "claude-haiku-5-5"
    agent_max_turns: int = 20
    agent_max_tokens_per_conversation: int = 30_000
    agent_history_messages: int = 12
    agency_name: str = "nossa agencia"
    allowed_reply_hosts: str = ""  # dominios que o agente pode citar (separados por virgula)
    followup_after_hours: int = 48
    max_followups: int = 2

    # --- Parte 4: WhatsApp, fechamento, entrega ---
    public_base_url: str = "http://localhost:8000"  # usado nos links de proposta/briefing/previa
    whatsapp_enabled: bool = False
    whatsapp_access_token: str | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_app_secret: str | None = None  # chave do HMAC X-Hub-Signature-256
    whatsapp_verify_token: str | None = None  # handshake GET do webhook
    whatsapp_api_version: str = "v23.0"
    whatsapp_template_language: str = "pt_BR"
    whatsapp_max_templates_per_day: int = 50  # respeite o tier atual do seu numero
    human_sla_minutes: int = 30
    proposal_validity_days: int = 7
    preview_ttl_days: int = 14
    payment_webhook_secret: str | None = None  # HMAC dos webhooks de pagamento (provedor futuro)

    # --- Parte 4: seguranca e observabilidade ---
    data_encryption_keys: str | None = None  # chaves Fernet separadas por virgula (a 1a cifra)
    redis_url: str | None = None
    rate_limit_enabled: bool = True
    metrics_enabled: bool = True
    sentry_dsn: str | None = None

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @model_validator(mode="after")
    def _no_weak_secrets_in_production(self):
        if self.is_production:
            for name in ("jwt_secret", "service_api_key"):
                value = getattr(self, name)
                if value in _DEFAULTS or value.startswith("troque") or len(value) < 32:
                    raise ValueError(f"{name} fraco: use `openssl rand -hex 32` em producao")
            if not self.data_encryption_keys:
                raise ValueError("DATA_ENCRYPTION_KEYS obrigatoria em producao (veja docs/SEGURANCA.md)")
            if self.whatsapp_enabled and not all(
                [self.whatsapp_access_token, self.whatsapp_phone_number_id,
                 self.whatsapp_app_secret, self.whatsapp_verify_token]
            ):
                raise ValueError("WhatsApp habilitado sem credenciais completas")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
