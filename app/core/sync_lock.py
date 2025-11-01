import asyncio
import logging

from redis import asyncio as aioredis  # type: ignore[import-not-found, import-untyped]

from app.core.settings import settings

logger = logging.getLogger(__name__)


class SyncLock:
    """Управление блокировками синхронизации через Redis."""

    def __init__(self) -> None:
        """Инициализация Redis клиента."""
        self._client: aioredis.Redis | None = None  # type: ignore[name-defined]
        self._initialized = False
        self._init_lock = asyncio.Lock()

    async def _get_client(self) -> aioredis.Redis | None:  # type: ignore[name-defined]
        """Получение Redis клиента с ленивой инициализацией."""
        if not self._initialized:
            async with self._init_lock:
                if not self._initialized:
                    try:
                        connection_params: dict[str, str | int | bool] = {
                            "decode_responses": True,
                            "socket_timeout": 2,
                            "socket_connect_timeout": 2,
                        }

                        if settings.REDIS_PASSWORD:
                            connection_params["password"] = settings.REDIS_PASSWORD

                        self._client = await aioredis.from_url(
                            f"redis://{settings.REDIS_HOST}:{settings.REDIS_PORT}/{settings.REDIS_DB}",
                            **connection_params,
                        )
                        await self._client.ping()  # type: ignore[misc]
                        logger.info("Подключение к Redis установлено: %s:%s", settings.REDIS_HOST, settings.REDIS_PORT)
                        self._initialized = True
                    except Exception as e:
                        logger.warning(
                            "Не удалось подключиться к Redis: %s. Синхронизация продолжится без защиты от циклов.", e
                        )
                        self._client = None
                        self._initialized = True

        return self._client

    async def set_amocrm_to_sheets_lock(self, row_index: int) -> None:
        """
        Установить блокировку: обновление идет из AmoCRM в Sheets.

        Args:
            row_index: Номер строки в таблице
        """
        client = await self._get_client()
        if client is None:
            return

        key = f"sync:amocrm_to_sheets:{row_index}"
        try:
            await client.setex(key, settings.SYNC_LOCK_TTL, "1")
            logger.debug("Установлена блокировка AmoCRM→Sheets для строки %s на %s сек", row_index, settings.SYNC_LOCK_TTL)
        except Exception as e:
            logger.warning("Не удалось установить блокировку в Redis: %s", e)

    async def check_amocrm_to_sheets_lock(self, row_index: int) -> bool:
        """
        Проверить, активна ли блокировка AmoCRM→Sheets.

        Args:
            row_index: Номер строки в таблице

        Returns:
            True если блокировка активна (нужно пропустить обработку)
        """
        client = await self._get_client()
        if client is None:
            return False

        key = f"sync:amocrm_to_sheets:{row_index}"
        try:
            exists = await client.exists(key)
            if exists:
                logger.info("Обнаружена блокировка AmoCRM→Sheets для строки %s, пропускаем обработку", row_index)
            return bool(exists)
        except Exception as e:
            logger.warning("Не удалось проверить блокировку в Redis: %s", e)
            return False

    async def close(self) -> None:
        """Закрыть соединение с Redis."""
        if self._client:
            try:
                await self._client.aclose()  # type: ignore[attr-defined]
                logger.info("Соединение с Redis закрыто")
            except Exception as e:
                logger.warning("Ошибка при закрытии соединения с Redis: %s", e)


sync_lock = SyncLock()
