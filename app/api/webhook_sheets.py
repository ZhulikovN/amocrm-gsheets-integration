from typing import Any

from fastapi import APIRouter, Header

from app.models.webhook_row import WebhookRow
from app.services.sheets_service import process_webhook_sheets

router = APIRouter(tags=["webhooks"])


@router.post("/webhook/sheets")
async def webhook_sheets(
    payload: WebhookRow,
    x_webhook_secret: str = Header(...),
) -> dict[str, Any]:
    """Обработка вебхука от Google Sheets."""
    return await process_webhook_sheets(payload, x_webhook_secret)
