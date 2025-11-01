import asyncio
import logging
import os
from typing import Any

from amocrm.v2 import Contact as _Contact  # type: ignore[import-untyped]
from amocrm.v2 import Lead as AmoLead  # type: ignore[import-untyped]
from amocrm.v2 import Pipeline, custom_field, tokens  # type: ignore[import-untyped]
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential  # type: ignore[import-untyped]

from app.core.settings import settings

logger = logging.getLogger(__name__)


class Contact(_Contact):  # type: ignore[misc]
    """Контакт с кастомными полями."""

    phone = custom_field.ContactPhoneField("Телефон")
    email = custom_field.ContactEmailField("Email")


def init_token_manager() -> None:
    """Инициализация менеджера токенов AmoCRM."""
    subdomain = settings.AMO_BASE_URL

    BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    token_dir = os.path.join(BASE_DIR, ".amocrm_tokens")

    os.makedirs(token_dir, exist_ok=True)

    tokens.default_token_manager(
        client_id=settings.AMO_CLIENT_ID,
        client_secret=settings.AMO_CLIENT_SECRET,
        subdomain=subdomain,
        redirect_url=settings.AMO_REDIRECT_URI,
        storage=tokens.FileTokensStorage(token_dir),
    )

    access_path = os.path.join(token_dir, "access_token.txt")
    refresh_path = os.path.join(token_dir, "refresh_token.txt")

    if os.path.exists(access_path) and os.path.exists(refresh_path):
        logger.info("Найдены сохранённые токены — используем их.")
    else:
        try:
            logger.info("Нет сохранённых токенов — инициализация через auth_code...")
            tokens.default_token_manager.init(code=settings.AMO_AUTH_CODE, skip_error=True)
            logger.info("Первичная инициализация выполнена, токены сохранены.")
        except Exception as e:
            logger.warning(
                "Не удалось инициализировать токены через auth_code: %s. Токены будут обновлены при первом запросе.", e
            )


init_token_manager()


class AmoCRMClient:
    """Клиент для взаимодействия с AmoCRM API."""

    def __init__(self) -> None:
        """Инициализация клиента AmoCRM."""
        self.base_url = settings.AMO_BASE_URL
        self.pipeline_id = settings.AMO_PIPELINE_ID
        self.status_id = settings.AMO_STATUS_ID

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def find_contact(
        self, phone: str | None = None, email: str | None = None, name: str | None = None
    ) -> dict[str, Any] | None:
        """
        Поиск контакта.
        Логика: сначала по email, если несколько - фильтруем по телефону и имени.

        Args:
            phone: Номер телефона
            email: Email адрес
            name: Имя контакта (для фильтрации при нескольких результатах)

        Returns:
            dict[str, Any] | None: Данные контакта или None если не найден
        """
        try:
            if email:
                contacts = await asyncio.to_thread(lambda: list(Contact.objects.filter(query=email)))
                logger.info("Найдено %s контактов по email %s", len(contacts), email)

                if len(contacts) == 1:
                    contact = contacts[0]
                    logger.info("Найден один контакт по email: id=%s", contact.id)
                    return {
                        "id": contact.id,
                        "name": contact.name,
                        "phone": phone,
                        "email": email,
                    }

                if len(contacts) > 1:
                    logger.info("Найдено несколько контактов, фильтруем по телефону и имени")

                    for contact in contacts:
                        phone_match = not phone or contact.phone == phone
                        name_match = not name or contact.name.lower() == name.lower()

                        if phone_match and name_match:
                            logger.info("Найден контакт по email+телефон+имя: id=%s", contact.id)
                            return {
                                "id": contact.id,
                                "name": contact.name,
                                "phone": phone,
                                "email": email,
                            }

                    contact = contacts[0]
                    logger.info("Точное совпадение не найдено, используем первый: id=%s", contact.id)
                    return {
                        "id": contact.id,
                        "name": contact.name,
                        "phone": phone,
                        "email": email,
                    }

            if phone:
                contacts = await asyncio.to_thread(lambda: list(Contact.objects.filter(query=phone)))
                if contacts:
                    contact = contacts[0]
                    logger.info("Найден контакт по телефону %s: id=%s", phone, contact.id)
                    return {
                        "id": contact.id,
                        "name": contact.name,
                        "phone": phone,
                        "email": email,
                    }

            logger.info("Контакт не найден")
            return None

        except Exception as e:
            logger.error("Ошибка при поиске контакта: %s", e)
            raise

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def update_contact(self, contact_id: int, name: str, phone: str | None = None, email: str | None = None) -> int:
        """Обновление существующего контакта."""
        try:
            contact = await asyncio.to_thread(Contact.objects.get, contact_id)

            updated = False

            if name and contact.name != name:
                contact.name = name
                updated = True

            if phone and contact.phone != phone:
                contact.phone = phone
                updated = True

            if email and contact.email != email:
                contact.email = email
                updated = True

            if updated:
                await asyncio.to_thread(contact.save)
                logger.info("Обновлён контакт: id=%s, name=%s, phone=%s, email=%s", contact_id, name, phone, email)
            else:
                logger.info("Контакт не изменился: id=%s", contact_id)

            return contact_id

        except Exception as e:
            logger.error("Ошибка при обновлении контакта: %s", e)
            raise

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def upsert_contact(self, name: str, phone: str | None = None, email: str | None = None) -> int:
        """Создание или обновление контакта."""
        try:
            existing = await self.find_contact(phone=phone, email=email, name=name)
            if existing:
                contact_id = existing["id"]
                contact = await asyncio.to_thread(Contact.objects.get, contact_id)

                updated = False

                if name and contact.name != name:
                    contact.name = name
                    updated = True

                if phone and contact.phone != phone:
                    contact.phone = phone
                    updated = True

                if email and contact.email != email:
                    contact.email = email
                    updated = True

                if updated:
                    await asyncio.to_thread(contact.save)
                    logger.info("Обновлён контакт: id=%s, name=%s, phone=%s, email=%s", contact_id, name, phone, email)
                else:
                    logger.info("Контакт не изменился: id=%s", contact_id)

                return contact_id

            def create_contact() -> int:
                contact = Contact()
                contact.name = name
                if phone:
                    contact.phone = phone
                if email:
                    contact.email = email
                contact.save()
                return contact.id

            new_contact_id = await asyncio.to_thread(create_contact)
            logger.info("Создан новый контакт: id=%s, name=%s, phone=%s, email=%s", new_contact_id, name, phone, email)
            return new_contact_id

        except Exception as e:
            logger.error("Ошибка при создании/обновлении контакта: %s", e)
            raise

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def find_lead(  # pylint: disable=too-many-branches
        self,
        email: str | None = None,
        name: str | None = None,
        lead_id: int | None = None,
    ) -> dict[str, Any] | None:
        """
        Поиск сделки по lead_id или email контакта.

        Args:
            email: Email для поиска контакта
            name: Имя для фильтрации при нескольких сделках
            lead_id: ID сделки для прямого поиска

        Returns:
            dict[str, Any] | None: Данные сделки или None если не найдена
        """
        try:
            if lead_id:
                try:
                    lead = await asyncio.to_thread(AmoLead.objects.get, lead_id)
                    logger.info("Найдена сделка по lead_id=%s", lead_id)
                    return {
                        "id": lead.id,
                        "name": lead.name,
                        "price": lead.price,
                    }
                except Exception as e:
                    logger.warning("Сделка с lead_id=%s не найдена: %s", lead_id, e)
                    return None

            if not email:
                logger.info("Email не указан и lead_id нет, поиск сделки невозможен")
                return None

            contact_data = await self.find_contact(email=email, name=name)
            if not contact_data:
                logger.info("Контакт с email %s не найден", email)
                return None

            contact_id = contact_data["id"]
            logger.info("Найден контакт: id=%s", contact_id)

            def find_leads_for_contact() -> list[Any]:
                all_leads = list(AmoLead.objects.filter())
                contact_leads = []
                for lead in all_leads:
                    try:
                        lead_contacts = lead.contacts
                        for lead_contact in lead_contacts:
                            if hasattr(lead_contact, "id") and lead_contact.id == contact_id:
                                contact_leads.append(lead)
                                break
                    except Exception:
                        continue
                return contact_leads

            contact_leads = await asyncio.to_thread(find_leads_for_contact)

            if not contact_leads:
                logger.info("Сделки для контакта id=%s не найдены", contact_id)
                return None

            if len(contact_leads) == 1:
                lead = contact_leads[0]
                logger.info("Найдена одна сделка для контакта: id=%s", lead.id)
                return {
                    "id": lead.id,
                    "name": lead.name,
                    "price": lead.price,
                }

            logger.info("Найдено %s сделок для контакта, фильтруем по имени", len(contact_leads))

            if name:
                for lead in contact_leads:
                    if name.lower() in lead.name.lower():
                        logger.info("Найдена сделка по имени '%s': id=%s", name, lead.id)
                        return {
                            "id": lead.id,
                            "name": lead.name,
                            "price": lead.price,
                        }

            lead = contact_leads[0]
            logger.info("Точное совпадение не найдено, используем первую сделку контакта: id=%s", lead.id)
            return {
                "id": lead.id,
                "name": lead.name,
                "price": lead.price,
            }

        except Exception as e:
            logger.error("Ошибка при поиске сделки: %s", e)
            raise

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def create_lead(
        self,
        name: str,
        contact_id: int,
        budget: float = 0,
    ) -> int:
        """
        Создание сделки.

        Args:
            name: Название сделки
            contact_id: ID контакта
            budget: Бюджет сделки

        Returns:
            int: ID созданной сделки
        """
        try:

            def create_lead_sync() -> int:
                pipeline = Pipeline.objects.get(self.pipeline_id)

                lead = AmoLead.objects.create(
                    name=name,
                    price=int(budget),
                    pipeline_id=pipeline.id,
                    status_id=self.status_id,
                )

                contact = Contact.objects.get(contact_id)
                lead.contacts.append(contact)
                lead.save()
                return lead.id

            lead_id = await asyncio.to_thread(create_lead_sync)
            logger.info(
                "Создана сделка: id=%s, name=%s, price=%s, pipeline=%s, status=%s, contact=%s",
                lead_id,
                name,
                budget,
                self.pipeline_id,
                self.status_id,
                contact_id,
            )
            return lead_id
        except Exception as e:
            logger.error("Ошибка при создании сделки: %s", e, exc_info=True)
            raise

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def upsert_lead(  # pylint: disable=too-many-positional-arguments
        self,
        name: str,
        contact_id: int,
        budget: float = 0,
        email: str | None = None,
        lead_id: int | None = None,
    ) -> int:
        """
        Создание или обновление сделки.

        Args:
            name: Название сделки
            contact_id: ID контакта
            budget: Бюджет сделки
            email: Email для поиска существующей сделки
            lead_id: ID сделки для прямого поиска

        Returns:
            int: ID сделки
        """
        try:
            existing_lead = await self.find_lead(email=email, name=name, lead_id=lead_id)

            if existing_lead:
                lead_id_found = existing_lead["id"]

                def update_lead_sync() -> tuple[int, bool]:
                    lead = AmoLead.objects.get(lead_id_found)
                    updated = False

                    if name and lead.name != name:
                        lead.name = name
                        updated = True

                    if budget and lead.price != int(budget):
                        lead.price = int(budget)
                        updated = True

                    if updated:
                        lead.save()

                    return lead_id_found, updated

                lead_id_result, was_updated = await asyncio.to_thread(update_lead_sync)

                if was_updated:
                    logger.info("Обновлена сделка: id=%s, name=%s, price=%s", lead_id_result, name, budget)
                else:
                    logger.info("Сделка не изменилась: id=%s", lead_id_result)

                return lead_id_result

            new_lead_id = await self.create_lead(name=name, contact_id=contact_id, budget=budget)
            logger.info("Создана новая сделка: id=%s", new_lead_id)
            return new_lead_id

        except Exception as e:
            logger.error("Ошибка при создании/обновлении сделки: %s", e)
            raise

    def lead_link(self, lead_id: int) -> str:
        """
        Генерация ссылки на сделку в AmoCRM.

        Args:
            lead_id: ID сделки

        Returns:
            str: URL сделки
        """
        return f"{self.base_url}/leads/detail/{lead_id}"

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def get_contact_info(self, contact_id: int) -> dict[str, Any] | None:
        """
        Получение полной информации о контакте.

        Args:
            contact_id: ID контакта

        Returns:
            dict[str, Any] | None: Данные контакта или None если не найден
        """
        try:

            def get_contact_data() -> dict[str, Any]:
                contact = Contact.objects.get(contact_id)

                phone = None
                email = None

                try:
                    phone = contact.phone
                except Exception:
                    pass

                try:
                    email = contact.email
                except Exception:
                    pass

                return {
                    "id": contact.id,
                    "name": contact.name,
                    "phone": phone,
                    "email": email,
                }

            contact_data = await asyncio.to_thread(get_contact_data)

            logger.info(
                "Получена информация о контакте: id=%s, name=%s, phone=%s, email=%s",
                contact_id,
                contact_data["name"],
                contact_data["phone"],
                contact_data["email"],
            )

            return contact_data

        except Exception as e:
            logger.error("Ошибка при получении информации о контакте %s: %s", contact_id, e)
            return None

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def get_lead_info(self, lead_id: int) -> dict[str, Any] | None:
        """
        Получение полной информации о сделке.

        Args:
            lead_id: ID сделки

        Returns:
            dict[str, Any] | None: Данные сделки или None если не найдена
        """
        try:

            def get_lead_data() -> dict[str, Any]:
                lead = AmoLead.objects.get(lead_id)

                status_id = getattr(lead.status, "id", None) if hasattr(lead, "status") else None
                status_name = getattr(lead.status, "name", None) if hasattr(lead, "status") else None
                pipeline_id = getattr(lead.pipeline, "id", None) if hasattr(lead, "pipeline") else None

                contact_id = None
                contact_name = None
                try:
                    lead_contacts = lead.contacts
                    contacts_list = list(lead_contacts) if lead_contacts else []

                    if contacts_list:
                        first_contact = contacts_list[0]
                        contact_id = getattr(first_contact, "id", None)
                        contact_name = getattr(first_contact, "name", None)
                except Exception as e:
                    logger.debug("Не удалось получить контакты сделки %s: %s", lead_id, e)

                return {
                    "id": lead.id,
                    "name": lead.name,
                    "price": lead.price,
                    "status_id": status_id,
                    "status_name": status_name,
                    "pipeline_id": pipeline_id,
                    "contact_id": contact_id,
                    "contact_name": contact_name,
                }

            lead_data = await asyncio.to_thread(get_lead_data)

            logger.info(
                "Получена информация о сделке: id=%s, name=%s, price=%s, status=%s, contact_id=%s",
                lead_id,
                lead_data["name"],
                lead_data["price"],
                lead_data["status_name"],
                lead_data["contact_id"],
            )

            return lead_data

        except Exception as e:
            logger.error("Ошибка при получении информации о сделке %s: %s", lead_id, e)
            return None


amocrm_client = AmoCRMClient()
