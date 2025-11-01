import hashlib
import re
import time


def normalize_phone(raw: str | None) -> str | None:
    """
    Нормализация телефона в формат +79991234567.

    Args:
        raw: Исходный телефон

    Returns:
        str | None: Нормализованный телефон или None
    """
    if not raw:
        return None

    digits = re.sub(r"\D", "", raw)

    if not digits:
        return None

    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    elif digits.startswith("9") and len(digits) == 10:
        digits = "7" + digits

    if len(digits) == 11 and digits.startswith("7"):
        return f"+{digits}"

    return f"+{digits}"


def make_external_id(phone: str | None, email: str | None) -> str:
    """
    Создание внешнего ID на основе телефона и email.

    Args:
        phone: Телефон
        email: Email

    Returns:
        str: Хэш внешнего ID
    """
    parts = []

    if phone:
        parts.append(normalize_phone(phone) or phone)
    if email:
        parts.append(email.lower().strip())

    if not parts:
        parts.append(str(time.time()))

    combined = "|".join(parts)
    return hashlib.md5(combined.encode()).hexdigest()[:16]
