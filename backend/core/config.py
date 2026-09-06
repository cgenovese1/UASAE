from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    app_name: str = "UASAE"
    app_env: str = "development"
    log_level: str = "INFO"

    # Database (Supabase PostgreSQL on T340)
    database_url: str = ""
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""

    # AI / LLM (ARGUS LiteLLM)
    litellm_base_url: str = "https://t340.tail909e11.ts.net/litellm"
    litellm_api_key: str = ""
    default_model: str = "qwen3:8b"
    reasoning_model: str = "qwen3:8b"

    # Object storage (S3-compatible / MinIO on T340)
    object_storage_endpoint: str = ""
    object_storage_access_key: str = ""
    object_storage_secret_key: str = ""
    object_storage_bucket: str = "uasae-evidence"

    # Event bus (Redis pub/sub on T340)
    redis_url: str = "redis://t340.tail909e11.ts.net:6379"

    # Execution
    max_browser_sessions: int = 4
    default_execution_timeout_seconds: int = 60
    verification_budget_seconds: int = 3600

    # Security
    secret_key: str = ""
    allowed_origins: list[str] = ["http://localhost:3000"]


settings = Settings()
