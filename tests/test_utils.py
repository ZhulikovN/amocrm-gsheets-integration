import pytest

from app.utils import make_external_id, normalize_phone


class TestNormalizePhone:
    """Тесты нормализации телефона."""

    def test_normalize_phone_with_plus_seven(self) -> None:
        """Тест с +7."""
        assert normalize_phone("+79991234567") == "+79991234567"

    def test_normalize_phone_with_eight(self) -> None:
        """Тест с 8."""
        assert normalize_phone("89991234567") == "+79991234567"

    def test_normalize_phone_with_nine(self) -> None:
        """Тест с 9."""
        assert normalize_phone("9991234567") == "+79991234567"

    def test_normalize_phone_with_formatting(self) -> None:
        """Тест с форматированием."""
        assert normalize_phone("+7 (999) 123-45-67") == "+79991234567"

    def test_normalize_phone_empty(self) -> None:
        """Тест пустого значения."""
        assert normalize_phone(None) is None
        assert normalize_phone("") is None

    def test_normalize_phone_invalid(self) -> None:
        """Тест невалидного телефона."""
        result = normalize_phone("abc")
        assert result is None


class TestMakeExternalId:
    """Тесты создания внешнего ID."""

    def test_make_external_id_with_phone(self) -> None:
        """Тест с телефоном."""
        result = make_external_id("+79991234567", None)
        assert len(result) == 16
        assert isinstance(result, str)

    def test_make_external_id_with_email(self) -> None:
        """Тест с email."""
        result = make_external_id(None, "test@example.com")
        assert len(result) == 16
        assert isinstance(result, str)

    def test_make_external_id_with_both(self) -> None:
        """Тест с телефоном и email."""
        result = make_external_id("+79991234567", "test@example.com")
        assert len(result) == 16
        assert isinstance(result, str)

    def test_make_external_id_consistent(self) -> None:
        """Тест консистентности."""
        result1 = make_external_id("+79991234567", "test@example.com")
        result2 = make_external_id("+79991234567", "test@example.com")
        assert result1 == result2

    def test_make_external_id_different(self) -> None:
        """Тест различия."""
        result1 = make_external_id("+79991234567", "test@example.com")
        result2 = make_external_id("+79991234568", "test@example.com")
        assert result1 != result2

