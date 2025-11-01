import logging

from fastapi import APIRouter, HTTPException, status

from app.services.import_service import import_existing_rows

logger = logging.getLogger(__name__)

router = APIRouter(tags=["import"])


@router.post("/import")
async def import_rows() -> dict[str, int]:
    """Импорт всех строк из Google Sheets."""
    try:
        return await import_existing_rows()
    except Exception as e:
        logger.error("Ошибка импорта: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        ) from e
