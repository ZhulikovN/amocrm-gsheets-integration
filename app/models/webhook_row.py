from pydantic import BaseModel, Field


class SheetLead(BaseModel):
    """Модель данных лида из Google Sheets."""

    name: str = Field(..., description="Имя клиента")
    phone: str | None = Field(None, description="Телефон клиента")
    email: str | None = Field(None, description="Email клиента")
    budget: float = Field(default=0, description="Бюджет сделки")
    external_id: str | None = Field(None, description="Внешний ID для дедупликации")


class WebhookRow(BaseModel):
    """Модель вебхука от Google Sheets."""

    row_index: int = Field(..., ge=2, description="Номер строки в таблице (начиная с 2)")
    data: SheetLead = Field(..., description="Данные лида")
