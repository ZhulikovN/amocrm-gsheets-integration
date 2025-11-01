import asyncio
import logging
from typing import Any

from fastapi import HTTPException, status

from app.core.amocrm_client import amocrm_client
from app.core.settings import settings
from app.core.sheets_client import sheets_client
from app.core.sync_lock import sync_lock
from app.core.utils import make_external_id, normalize_phone
from app.models.webhook_row import WebhookRow

logger = logging.getLogger(__name__)


async def process_webhook_sheets(
    payload: WebhookRow,
    x_webhook_secret: str,
) -> dict[str, Any]:
    """Обработка вебхука от Google Sheets с валидацией и обработкой ошибок."""
    if x_webhook_secret != settings.WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    row_index = payload.row_index
    lead_data = payload.data
    phone = normalize_phone(lead_data.phone)
    external_id = make_external_id(phone, lead_data.email)

    try:
        return await _process_webhook_sheets_internal(payload, row_index, phone, external_id)
    except Exception as e:
        error_msg = str(e)[:50]
        logger.error(
            "Ошибка обработки webhook: row=%s, external_id=%s, error=%s",
            row_index,
            external_id,
            error_msg,
            exc_info=True,
        )
        try:
            await sheets_client.update_cells(row_index=row_index, mapping={"status": f"error:{error_msg}"})
        except Exception as update_error:
            logger.error("Не удалось обновить статус ошибки в таблице: %s", update_error)

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_msg,
        ) from e


async def _process_webhook_sheets_internal(  # pylint: disable=too-many-locals,too-many-statements
    payload: WebhookRow,
    row_index: int,
    phone: str | None,
    external_id: str,
) -> dict[str, Any]:
    """Внутренняя обработка вебхука от Google Sheets."""
    lead_data = payload.data

    if await sync_lock.check_amocrm_to_sheets_lock(row_index):
        logger.info(
            "Пропускаем обработку строки %s - недавно обновлено из AmoCRM (защита от цикла)",
            row_index,
        )
        return {"success": True, "skipped": "sync_lock_active", "row_index": row_index}

    existing_lead_id = None
    existing_contact_id = None
    try:
        rows = await sheets_client.read_all_rows()
        current_row = rows[row_index - 2] if row_index - 2 < len(rows) else None
        if current_row:
            if str(current_row.get("amo_deal_id", "")).strip():
                existing_lead_id = int(current_row["amo_deal_id"])
                logger.info("Найден существующий lead_id=%s в строке %s", existing_lead_id, row_index)
            if str(current_row.get("amo_contact_id", "")).strip():
                existing_contact_id = int(current_row["amo_contact_id"])
                logger.info("Найден существующий contact_id=%s в строке %s", existing_contact_id, row_index)
    except Exception as e:
        logger.warning("Не удалось прочитать строку %s: %s", row_index, e)

    client = await sync_lock._get_client()  # pylint: disable=protected-access
    lock_key = f"creating_lead:{row_index}"
    locked_by_me = False

    if not existing_lead_id:
        if client:
            is_locked = await client.exists(lock_key)

            if is_locked:  # pylint: disable=too-many-nested-blocks
                logger.info("Сделка для строки %s создается, ожидаем запись amo_deal_id в таблицу (3 сек)", row_index)
                await asyncio.sleep(3)

                try:
                    rows = await sheets_client.read_all_rows()
                    current_row = rows[row_index - 2] if row_index - 2 < len(rows) else None
                    if current_row and str(current_row.get("amo_deal_id", "")).strip():
                        existing_lead_id = int(current_row["amo_deal_id"])
                        logger.info("После ожидания найден amo_deal_id=%s, продолжаем обновление", existing_lead_id)
                        if str(current_row.get("amo_contact_id", "")).strip():
                            existing_contact_id = int(current_row["amo_contact_id"])
                    else:
                        logger.info("После ожидания amo_deal_id не найден, пропускаем webhook")
                        return {"success": False, "skipped": "lead_still_creating", "row_index": row_index}
                except Exception as e:
                    logger.warning("Не удалось перечитать строку %s после ожидания: %s", row_index, e)
                    return {"success": False, "skipped": "read_error_after_wait", "row_index": row_index}

            if not existing_lead_id:
                locked_by_me = await client.set(lock_key, "1", ex=10, nx=True)

                if not locked_by_me:
                    logger.info("Сделка для строки %s уже создаётся, пропускаем webhook", row_index)
                    return {"success": False, "skipped": "lead_creating", "row_index": row_index}

                logger.info("Установлена блокировка создания для строки %s", row_index)

    if existing_lead_id:
        logger.info("Сделка существует (id=%s), обновляем БЕЗ блокировки", existing_lead_id)

    try:
        logger.info(
            "Получен webhook: row=%s, name=%s, phone=%s, email=%s, budget=%s, external_id=%s",
            row_index,
            lead_data.name,
            lead_data.phone,
            lead_data.email,
            lead_data.budget,
            external_id,
        )

        logger.info(
            "Нормализованные данные: phone=%s, email=%s, budget=%s, external_id=%s",
            phone,
            lead_data.email,
            lead_data.budget,
            external_id,
        )

        if existing_contact_id:
            logger.info(
                "Обновляем существующий контакт %s (имя=%s, телефон=%s, email=%s)",
                existing_contact_id,
                lead_data.name,
                phone,
                lead_data.email,
            )
            contact_id = await amocrm_client.update_contact(
                contact_id=existing_contact_id,
                name=lead_data.name,
                phone=phone,
                email=lead_data.email,
            )
        else:
            logger.info(
                "Контакт не найден в строке, выполняем upsert (имя=%s, телефон=%s, email=%s)",
                lead_data.name,
                phone,
                lead_data.email,
            )
            contact_id = await amocrm_client.upsert_contact(
                name=lead_data.name,
                phone=phone,
                email=lead_data.email,
            )

        lead_id = await amocrm_client.upsert_lead(
            name=lead_data.name,
            contact_id=contact_id,
            budget=lead_data.budget,
            email=lead_data.email,
            lead_id=existing_lead_id,
        )
        lead_link = amocrm_client.lead_link(lead_id)

        lead_info = await amocrm_client.get_lead_info(lead_id)
        status = lead_info.get("status_name", "created") if lead_info else "created"

        await sheets_client.update_cells(
            row_index=row_index,
            mapping={
                "amo_deal_id": str(lead_id),
                "amo_contact_id": str(contact_id),
                "amo_link": lead_link,
                "status": status,
                "external_id": external_id,
            },
        )

        logger.info(
            "Обработана строка %s: lead_id=%s, contact_id=%s, external_id=%s",
            row_index,
            lead_id,
            contact_id,
            external_id,
        )
        return {"success": True, "lead_id": lead_id, "contact_id": contact_id}

    finally:
        if locked_by_me and client:
            try:
                await client.delete(lock_key)
                logger.debug("Снята блокировка создания для строки %s", row_index)
            except Exception as e:
                logger.warning("Не удалось снять блокировку строки %s: %s", row_index, e)
