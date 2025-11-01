from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    """Проверка статуса приложения."""
    return {"status": "ok"}
