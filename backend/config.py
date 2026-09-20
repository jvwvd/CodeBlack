from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    APP_ENV: str = "development"

    SUPABASE_URL: str | None = None
    SUPABASE_KEY: str | None = None
    GEMINI_API_KEY: str | None = None
    FRONTEND_URL: str | None = None


settings = Settings()
