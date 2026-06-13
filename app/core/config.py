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
    SEARXNG_URL: str = "http://localhost:8080"
    MAX_CONCURRENT_FETCHES: int = 5
    PLAYWRIGHT_TIMEOUT_MS: int = 30000
    HTML_STORAGE_DIR: str = "storage/html"
    MAX_CLAIM_EXTRACTION_PAGES: int = 3
    MAX_RESEARCH_ROUNDS: int = 3
    CONFIDENCE_THRESHOLD: float = 0.8


settings = Settings()
