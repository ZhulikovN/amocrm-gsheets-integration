import asyncio
import logging
import threading
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

from app.core.settings import settings

logger = logging.getLogger(__name__)


class SheetsClient:
    """Клиент для взаимодействия с Google Sheets."""

    def __init__(self) -> None:
        """Инициализация клиента Google Sheets."""
        self.spreadsheet_id = settings.GOOGLE_SPREADSHEET_ID
        self.worksheet_name = settings.GOOGLE_WORKSHEET_NAME
        self._client: gspread.Client | None = None
        self._worksheet: gspread.Worksheet | None = None
        self._headers: list[str] = []
        self._init_lock = threading.Lock()

    def _get_credentials(self) -> Credentials:
        """
        Получение credentials из service account JSON файла.

        Returns:
            Credentials: Google OAuth2 credentials
        """
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        return Credentials.from_service_account_file(
            settings.GOOGLE_SERVICE_ACCOUNT_JSON,
            scopes=scopes,
        )

    def _get_worksheet(self) -> gspread.Worksheet:
        """
        Получение worksheet объекта.

        Returns:
            gspread.Worksheet: Объект листа таблицы
        """
        if self._worksheet is None:
            with self._init_lock:
                if self._worksheet is None:
                    if self._client is None:
                        credentials = self._get_credentials()
                        self._client = gspread.authorize(credentials)

                    spreadsheet = self._client.open_by_key(self.spreadsheet_id)
                    self._worksheet = spreadsheet.worksheet(self.worksheet_name)

                    self._headers = self._worksheet.row_values(1)
                    logger.info("Загружены заголовки: %s", self._headers)

        return self._worksheet

    async def read_all_rows(self) -> list[dict[str, Any]]:
        """
        Чтение всех строк таблицы как список словарей.

        Первая строка считается заголовками.
        Индексация строк начинается с 1 (строка 1 - заголовки).

        Returns:
            list[dict[str, Any]]: Список словарей, где ключи - названия колонок
        """

        def read_rows_sync() -> list[dict[str, Any]]:
            worksheet = self._get_worksheet()
            all_values = worksheet.get_all_values()

            if not all_values:
                logger.warning("Таблица пустая")
                return []

            headers = all_values[0]
            rows = all_values[1:]

            result: list[dict[str, Any]] = []
            for row in rows:
                while len(row) < len(headers):
                    row.append("")

                row_dict = {headers[i]: row[i] for i in range(len(headers))}
                result.append(row_dict)

            return result

        result = await asyncio.to_thread(read_rows_sync)
        logger.info("Прочитано %s строк из таблицы", len(result))
        return result

    async def update_cells(self, row_index: int, mapping: dict[str, Any]) -> None:
        """
        Обновление ячеек в строке по названиям колонок.

        Args:
            row_index: Номер строки (1 - заголовки, 2 - первая строка данных)
            mapping: Словарь {название_колонки: значение}
        """
        if row_index < 2:
            raise ValueError("row_index должен быть >= 2 (строка 1 - заголовки)")

        def update_cells_sync() -> int:
            worksheet = self._get_worksheet()
            headers = self._headers

            updates: list[dict[str, Any]] = []
            for col_name, value in mapping.items():
                if col_name not in headers:
                    logger.warning("Колонка '%s' не найдена в заголовках", col_name)
                    continue

                col_index = headers.index(col_name) + 1
                cell_address = gspread.utils.rowcol_to_a1(row_index, col_index)

                updates.append(
                    {
                        "range": cell_address,
                        "values": [[str(value)]],
                    }
                )

            if updates:
                worksheet.batch_update(updates)

            return len(updates)

        update_count = await asyncio.to_thread(update_cells_sync)
        if update_count > 0:
            logger.info("Обновлено %s ячеек в строке %s", update_count, row_index)

    async def find_row_by_deal_id(self, deal_id: int | str) -> int | None:
        """
        Поиск номера строки по amo_deal_id.

        Args:
            deal_id: ID сделки из AmoCRM

        Returns:
            int | None: Номер строки (начиная с 2) или None
        """

        def find_row_sync() -> int | None:
            worksheet = self._get_worksheet()
            headers = self._headers

            if "amo_deal_id" not in headers:
                logger.warning("Колонка 'amo_deal_id' не найдена в заголовках")
                return None

            col_index = headers.index("amo_deal_id") + 1
            col_values = worksheet.col_values(col_index)

            deal_id_str = str(deal_id)
            for i, value in enumerate(col_values[1:], start=2):
                if value == deal_id_str:
                    return i

            return None

        row_index = await asyncio.to_thread(find_row_sync)
        if row_index:
            logger.info("Найдена строка %s с amo_deal_id=%s", row_index, deal_id)
        else:
            logger.info("Строка с amo_deal_id=%s не найдена", deal_id)
        return row_index

    async def find_row_by_external_id(self, external_id: str) -> int | None:
        """
        Поиск строки по значению в колонке external_id.

        Args:
            external_id: Значение для поиска

        Returns:
            int | None: Номер строки (2-based) или None если не найдено
        """

        def find_row_sync() -> int | None:
            worksheet = self._get_worksheet()
            headers = self._headers

            if "external_id" not in headers:
                logger.error("Колонка 'external_id' не найдена в заголовках")
                return None

            col_index = headers.index("external_id") + 1
            col_values = worksheet.col_values(col_index)

            for i, value in enumerate(col_values[1:], start=2):
                if value == external_id:
                    return i

            return None

        row_index = await asyncio.to_thread(find_row_sync)
        if row_index:
            logger.info("Найдена строка %s с external_id=%s", row_index, external_id)
        else:
            logger.info("Строка с external_id=%s не найдена", external_id)
        return row_index


sheets_client = SheetsClient()
