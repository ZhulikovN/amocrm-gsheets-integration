import logging
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):

    GOOGLE_SERVICE_ACCOUNT_JSON: str = Field(
        default="./secrets/amocrm-integration-476618-492ca37a3da3.json",
        description="Путь до JSON-файла сервисного аккаунта Google Cloud",
    )
    GOOGLE_SPREADSHEET_ID: str = Field(
        ...,
        description="ID Google-таблицы (из URL)",
    )
    GOOGLE_WORKSHEET_NAME: str = Field(
        default="Лист1",
        description="Название листа в таблице (по умолчанию Лист1)",
    )

    AMO_BASE_URL: str = Field(
        default="https://systemkov.amocrm.ru",
        description="Базовый URL AmoCRM аккаунта",
    )
    AMO_CLIENT_ID: str = Field(..., description="Client ID интеграции AmoCRM")
    AMO_CLIENT_SECRET: str = Field(..., description="Client Secret интеграции AmoCRM")
    AMO_REDIRECT_URI: str = Field(
        default="https://example.com/oauth/callback",
        description="Redirect URI, указанный при создании интеграции AmoCRM",
    )
    AMO_AUTH_CODE: str = Field(
        ...,
        description="Authorization code для первичного получения токена",
    )
    AMO_ACCESS_TOKEN: str = Field(
        ...,
        description="Access Token AmoCRM (для запросов к API)",
    )
    AMO_REFRESH_TOKEN: str = Field(
        ...,
        description="Refresh Token AmoCRM (для обновления access токена)",
    )
    AMO_PIPELINE_ID: int = Field(
        default=00000,
        description="ID воронки, где создаются сделки (из ТЗ)",
    )
    AMO_STATUS_ID: int = Field(
        default=00000,
        description="ID этапа 'Новая заявка' (из ТЗ)",
    )

    APP_HOST: str = Field(default="0.0.0.0", description="Хост FastAPI-приложения")
    APP_PORT: int = Field(default=8080, description="Порт приложения")
    LOG_LEVEL: str = Field(default="INFO", description="Уровень логирования")
    WEBHOOK_SECRET: str = Field(..., description="Секрет для проверки подписи вебхука")

    REDIS_HOST: str = Field(default="localhost", description="Хост Redis сервера")
    REDIS_PORT: int = Field(default=6379, description="Порт Redis сервера")
    REDIS_DB: int = Field(default=0, description="Номер базы данных Redis")
    REDIS_PASSWORD: str | None = Field(default=None, description="Пароль для Redis (опционально)")
    SYNC_LOCK_TTL: int = Field(default=10, description="Время блокировки синхронизации в секундах")

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @property
    def log_level_value(self) -> int:
        """Возвращает числовой уровень логирования для logging.basicConfig."""
        return getattr(logging, self.LOG_LEVEL.upper(), logging.INFO)


settings = Settings()  # type: ignore[call-arg]
if not Path(settings.GOOGLE_SERVICE_ACCOUNT_JSON).is_absolute():
    base_path = Path(__file__).parent.parent.parent
    settings.GOOGLE_SERVICE_ACCOUNT_JSON = str(base_path / settings.GOOGLE_SERVICE_ACCOUNT_JSON)
