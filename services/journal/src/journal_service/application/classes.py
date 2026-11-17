from collections.abc import Callable
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from journal_service.application.ports.errors import (
    InvalidClassDataError,
)
from journal_service.application.ports.unit_of_work import UnitOfWork
from journal_service.domain.school_class import Class

# SQLAlchemy передаёт OFFSET PostgreSQL как знаковый BIGINT.
MAX_CLASS_OFFSET = 2**63 - 1


class CreateClassCommand(BaseModel):
    """Данные для создания школьного класса."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    name: str
    study_year: int = Field(ge=1900, le=9998)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        """Очищает имя и проверяет существующие ограничения класса.

        Args:
            value: Имя из входной команды.

        Returns:
            Имя без внешних пробелов.

        Raises:
            ValueError: Имя пустое, слишком длинное или содержит NUL.
        """
        value = value.strip()
        if not 1 <= len(value) <= 64 or "\x00" in value:
            raise ValueError("Invalid class name")
        return value


class ListClassesQuery(BaseModel):
    """Параметры чтения страницы классов; None отключает фильтр по году."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    study_year: int | None = Field(default=None, ge=1900, le=9998)
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0, le=MAX_CLASS_OFFSET)


class ClassResult(BaseModel):
    """Данные сохранённого класса для результата прикладного сценария."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: int
    name: str
    study_year: int
    created_at: AwareDatetime


class LookupClassesQuery(BaseModel):
    """Ограниченный пакет классов без произвольных дополнительных параметров."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    ids: list[Annotated[int, Field(strict=True, ge=1, le=2147483647)]] = Field(
        max_length=1000
    )

    @field_validator("ids")
    @classmethod
    def unique_ids(cls, value):
        """Не допускает повторяющиеся идентификаторы пакета."""
        if len(value) != len(set(value)):
            raise ValueError("Duplicate class IDs")
        return value


class LookupClassesHandler:
    """Читает пакет названий через один репозиторий и одну короткую транзакцию."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    async def handle(self, query: LookupClassesQuery) -> list[ClassResult]:
        """Возвращает только существующие классы, не создавая фиктивных названий."""
        async with self._uow_factory() as uow:
            rows = await uow.classes.get_classes_by_ids(query.ids)
        return [
            ClassResult(
                id=row.id,
                name=row.name,
                study_year=row.study_year,
                created_at=row.created_at,
            )
            for row in rows
        ]


class CreateClassHandler:
    """Создаёт класс в одной транзакции и возвращает сохранённые данные."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        """Получает фабрику транзакций.

        Args:
            uow_factory: Фабрика отдельного Unit of Work для сценария.
        """
        self._uow_factory = uow_factory

    async def handle(self, command: CreateClassCommand) -> ClassResult:
        """Проверяет данные класса и сохраняет их до возврата результата.

        Args:
            command: Имя класса и учебный год.

        Returns:
            Данные класса после успешного выхода из Unit of Work.

        Raises:
            InvalidClassDataError: Имя или учебный год недопустимы.
            DuplicateClassError: Класс с таким именем и годом уже существует.
        """
        try:
            school_class = Class(name=command.name, study_year=command.study_year)
        except ValueError as exc:
            raise InvalidClassDataError from exc

        async with self._uow_factory() as uow:
            saved_class = await uow.classes.create_class(school_class)

        return ClassResult(
            id=saved_class.id,
            name=saved_class.name,
            study_year=saved_class.study_year,
            created_at=saved_class.created_at,
        )


class ListClassesHandler:
    """Читает страницу классов и возвращает данные прикладного результата."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        """Получает фабрику транзакций.

        Args:
            uow_factory: Фабрика отдельного Unit of Work для сценария.
        """
        self._uow_factory = uow_factory

    async def handle(self, query: ListClassesQuery) -> list[ClassResult]:
        """Получает классы по параметрам запроса через отдельный Unit of Work.

        Args:
            query: Необязательный год, размер страницы и смещение.

        Returns:
            Классы в порядке репозитория; пустой список, если записей нет.

        """
        async with self._uow_factory() as uow:
            school_classes = await uow.classes.list_classes(
                study_year=query.study_year,
                limit=query.limit,
                offset=query.offset,
            )

        result = []

        for school_class in school_classes:
            result.append(
                ClassResult(
                    id=school_class.id,
                    name=school_class.name,
                    study_year=school_class.study_year,
                    created_at=school_class.created_at,
                )
            )

        return result
