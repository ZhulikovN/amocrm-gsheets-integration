import logging

from fastapi import FastAPI  # type: ignore[import-not-found, import-untyped] # pylint: disable=import-error

from app.api import health, import_routes, webhook_amocrm, webhook_sheets
from app.core.settings import settings
from app.core.sync_lock import sync_lock
from app.services.import_service import import_existing_rows

logging.basicConfig(
    level=settings.log_level_value,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="AmoCRM-GSheets Integration")

app.include_router(health.router)
app.include_router(webhook_sheets.router)
app.include_router(webhook_amocrm.router)
app.include_router(import_routes.router)


@app.on_event("startup")
async def on_startup() -> None:
    """Автоимпорт существующих строк при старте приложения."""
    logger.info("Запуск автоимпорта строк при старте приложения...")
    try:
        result = await import_existing_rows()
        logger.info(
            "Автоимпорт завершен: создано=%s, пропущено=%s, ошибок=%s",
            result["created"],
            result["skipped"],
            result["errors"],
        )
    except Exception as e:
        logger.error("Ошибка при автоимпорте: %s", e, exc_info=True)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    """Закрытие соединений при остановке приложения."""
    logger.info("Закрытие соединения с Redis...")
    await sync_lock.close()
