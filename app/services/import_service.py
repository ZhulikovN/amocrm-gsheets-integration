import asyncio
import logging

from app.core.amocrm_client import amocrm_client
from app.core.sheets_client import sheets_client
from app.core.utils import make_external_id, normalize_phone

logger = logging.getLogger(__name__)


async def import_existing_rows() -> dict[str, int]:  # pylint: disable=too-many-locals
    """Импорт строк без amo_deal_id из Google Sheets."""
    rows = await sheets_client.read_all_rows()

    semaphore = asyncio.Semaphore(2)

    tasks = []
    created = 0
    skipped = 0
    errors = 0

    for i, row in enumerate(rows, start=2):
        amo_deal_id = row.get("amo_deal_id", "").strip()
        external_id_existing = row.get("external_id", "").strip()

        if amo_deal_id or external_id_existing:
            skipped += 1
            continue

        name = row.get("name", "").strip()
        if not name:
            skipped += 1
            continue

        phone_raw = row.get("phone", "").strip()
        email = row.get("email", "").strip()
        budget_raw = row.get("budget", "0").strip()

        try:
            budget = float(budget_raw) if budget_raw else 0
        except ValueError:
            budget = 0

        phone = normalize_phone(phone_raw)
        external_id = make_external_id(phone, email)

        tasks.append(_process_row(i, name, phone, email, budget, external_id, semaphore))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, Exception):
            errors += 1
        elif result:
            created += 1

    return {"created": created, "skipped": skipped, "errors": errors}


async def _process_row(  # pylint: disable=too-many-positional-arguments
    row_index: int,
    name: str,
    phone: str | None,
    email: str | None,
    budget: float,
    external_id: str,
    semaphore: asyncio.Semaphore,
) -> bool:
    """Обработка одной строки при импорте с ограничением параллелизма."""
    async with semaphore:
        try:
            contact_id = await amocrm_client.upsert_contact(name=name, phone=phone, email=email)
            lead_id = await amocrm_client.create_lead(name=name, contact_id=contact_id, budget=budget)
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

            logger.info("Импортирована строка %s: lead_id=%s, external_id=%s", row_index, lead_id, external_id)
            return True

        except Exception as e:
            logger.error("Ошибка импорта строки %s, external_id=%s: %s", row_index, external_id, e)

            try:
                await sheets_client.update_cells(row_index=row_index, mapping={"status": f"error:{str(e)[:50]}"})
            except Exception:
                pass

            return False
