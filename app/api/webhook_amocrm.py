from fastapi import APIRouter, Request

from app.services.amocrm_service import process_webhook_amocrm

router = APIRouter(tags=["webhooks"])


@router.post("/webhook/amocrm")
async def webhook_amocrm(request: Request) -> dict[str, str]:
    """Обработка вебхука от AmoCRM."""
    return await process_webhook_amocrm(request)
