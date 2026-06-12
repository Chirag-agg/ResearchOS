from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_ignore_empty=True, extra="ignore"
    )

    PROJECT_NAME: str = "ResearchOS"
    API_V1_STR: str = "/api/v1"
    DATABASE_URL: str = "sqlite+aiosqlite:///./research_os.db"
    OLLAMA_API_URL: str = "http://localhost:11434"
    LLM_MODEL: str = "llama3"


settings = Settings()
