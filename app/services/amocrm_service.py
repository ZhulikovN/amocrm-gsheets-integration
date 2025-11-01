import logging

from fastapi import HTTPException, Request, status

from app.core.amocrm_client import amocrm_client
from app.core.sheets_client import sheets_client
from app.core.sync_lock import sync_lock

logger = logging.getLogger(__name__)


async def process_webhook_amocrm(request: Request) -> dict[str, str]:
    """Обработка вебхука от AmoCRM."""
    try:
        content_type = request.headers.get("content-type", "")

        if "application/json" in content_type:
            form_data = await request.json()
        else:
            form = await request.form()
            form_data = dict(form)

        logger.info("Получен вебхук от AmoCRM, Content-Type: %s", content_type)

        lead_id_str = form_data.get("leads[update][0][id]")
        if not lead_id_str:
            logger.info("Вебхук не содержит обновлений сделок")
            return {"status": "ok"}

        lead_id = int(lead_id_str)
        logger.info("Обработка обновления сделки: lead_id=%s", lead_id)

        row_index = await sheets_client.find_row_by_deal_id(lead_id)
        if not row_index:
            logger.warning("Строка для сделки %s не найдена в таблице", lead_id)
            return {"status": "ok", "message": "lead not found in sheets"}

        rows = await sheets_client.read_all_rows()
        current_row = rows[row_index - 2] if row_index - 2 < len(rows) else None
        stored_contact_id = None
        if current_row and str(current_row.get("amo_contact_id", "")).strip():
            try:
                stored_contact_id = int(current_row["amo_contact_id"])
            except (ValueError, TypeError):
                pass

        lead_info = await amocrm_client.get_lead_info(lead_id)
        if not lead_info:
            logger.warning("Не удалось получить информацию о сделке %s", lead_id)
            return {"status": "ok", "message": "lead info not available"}

        mapping = {}

        if lead_info.get("name"):
            mapping["name"] = str(lead_info["name"])

        if lead_info.get("price") is not None:
            mapping["budget"] = str(lead_info["price"])

        if lead_info.get("status_name"):
            mapping["status"] = str(lead_info["status_name"])

        contact_id = lead_info.get("contact_id") or stored_contact_id

        if contact_id:
            contact_info = await amocrm_client.get_contact_info(contact_id)
            if contact_info:
                if contact_info.get("phone"):
                    mapping["phone"] = str(contact_info["phone"])

                if contact_info.get("email"):
                    mapping["email"] = str(contact_info["email"])

                if contact_info.get("name"):
                    mapping["name"] = str(contact_info["name"])

        if mapping:
            await sync_lock.set_amocrm_to_sheets_lock(row_index)
            await sheets_client.update_cells(row_index=row_index, mapping=mapping)
            logger.info("Обновлена строка %s для сделки %s: %s (с блокировкой синхронизации)", row_index, lead_id, mapping)

        return {"status": "ok", "updated": "1"}

    except Exception as e:
        logger.error("Ошибка обработки вебхука AmoCRM: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e
