from pydantic import Field
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: str
    TRANSLATE_API: Optional[str] = Field(default=None)
    TRANSLATE_API_KEY: Optional[str] = Field(default=None)
    OWNER_USER_ID: Optional[int] = Field(default=None)
    DB_PATH: str = Field(default="./data/bot.db")
    ALLOW_BROADCAST_FROM_GROUPS: bool = Field(default=False)
    BROADCAST_MAX_PER_HOUR: int = Field(default=5)
    BROADCAST_MAX_GROUPS: int = Field(default=500)
    MEDIA_MAX_BYTES: int = Field(default=10485760)
    LOG_FILE: str = Field(default="./logs/bot.log")
    SKIP_PREFIX: str = Field(default="/notranslate")
    DEFAULT_TARGET_LANG: str = Field(default="auto")
    
    # LLM Fallback Configuration
    LLM_API_KEY: Optional[str] = Field(default=None)
    LLM_API_BASE: str = Field(default="https://api.openai.com/v1")
    LLM_API_ENDPOINT: Optional[str] = Field(default=None)
    LLM_MODEL: str = Field(default="gpt-4o-mini")

    # Dashboard Auth
    DASHBOARD_USERNAME: str = Field(default="admin")
    DASHBOARD_PASSWORD: str = Field(default="9999")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
