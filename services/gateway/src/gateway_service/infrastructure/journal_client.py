"""Клиенты Journal: ограниченные чтения и принципал записи уроков."""

from datetime import date
from enum import Enum
from typing import Literal
from uuid import UUID

import httpx
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
)


class JournalUnavailableError(Exception):
    """Journal не подтвердил данные или нарушил контракт ответа."""


class CurrentClassPeriod(BaseModel):
    """Проверенный открытый период именно запрошенного ученика."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: int = Field(strict=True, ge=1)
    student_id: UUID
    class_id: int = Field(strict=True, ge=1, le=2147483647)
    joined_at: AwareDatetime
    left_at: AwareDatetime | None


class ClassNameResponse(BaseModel):
    """Читаемое название класса без доступа к его изменению."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    id: int = Field(strict=True, ge=1, le=2147483647)
    name: str = Field(strict=True, min_length=1, max_length=64)
    study_year: int = Field(strict=True, ge=1900, le=9998)
    created_at: AwareDatetime


class JournalClient:
    """Использует свой read-токен и HTTP-пул, управляемый lifespan Gateway."""

    def __init__(self, http_client: httpx.AsyncClient, service_token: str) -> None:
        self._http_client = http_client
        self._headers = {"Authorization": f"Bearer {service_token}"}

    async def get_current_class_id(self, student_id: UUID) -> int | None:
        """Возвращает None только при подтверждённом отсутствии текущего периода.

        Args:
            student_id: UUID из авторизации Gateway.

        Returns:
            ID текущего класса либо None.

        Raises:
            JournalUnavailableError: Сеть, статус, закрытый или чужой период.
        """
        try:
            response = await self._http_client.get(
                f"/internal/students/{student_id}/current-class-period",
                headers=self._headers,
                timeout=5.0,
                follow_redirects=False,
            )
            if response.status_code == 404:
                return None
            if response.status_code != 200:
                raise JournalUnavailableError
            period = CurrentClassPeriod.model_validate_json(response.content)
        except (httpx.HTTPError, ValidationError) as exc:
            raise JournalUnavailableError from exc
        if period.student_id != student_id or period.left_at is not None:
            raise JournalUnavailableError
        return period.class_id

    async def list_current_student_ids(self, class_id: int) -> list[UUID]:
        """Читает текущий состав страницами, не скрывая превышение1000учеников."""
        ids = []
        try:
            for offset in range(0, 1100, 100):
                response = await self._http_client.get(
                    f"/internal/classes/{class_id}/current-periods",
                    params={"limit": 100, "offset": offset},
                    headers=self._headers,
                    timeout=5.0,
                    follow_redirects=False,
                )
                if response.status_code != 200:
                    raise JournalUnavailableError
                rows = TypeAdapter(list[CurrentClassPeriod]).validate_json(
                    response.content
                )
                if len(rows) > 100 or any(
                    row.class_id != class_id or row.left_at is not None for row in rows
                ):
                    raise JournalUnavailableError
                ids.extend(row.student_id for row in rows)
                if len(set(ids)) != len(ids):
                    raise JournalUnavailableError
                if len(ids) > 1000:
                    raise JournalUnavailableError
                if len(rows) < 100:
                    return ids
        except (httpx.HTTPError, ValidationError) as exc:
            raise JournalUnavailableError from exc
        raise JournalUnavailableError

    async def get_class_names(self, class_ids: list[int]) -> dict[int, str]:
        """Проверяет полноту названий одним запросом, а не на каждую карточку."""
        ids = sorted(set(class_ids))
        if not ids:
            return {}
        if len(ids) > 1000:
            raise JournalUnavailableError
        try:
            response = await self._http_client.post(
                "/internal/classes/lookup",
                json={"ids": ids},
                headers=self._headers,
                timeout=5.0,
                follow_redirects=False,
            )
            if response.status_code != 200:
                raise JournalUnavailableError
            rows = TypeAdapter(list[ClassNameResponse]).validate_json(response.content)
        except (httpx.HTTPError, ValidationError) as exc:
            raise JournalUnavailableError from exc
        if len(rows) != len(ids) or {row.id for row in rows} != set(ids):
            raise JournalUnavailableError
        return {row.id: row.name for row in rows}

    async def list_classes(self, *, limit: int, offset: int) -> list[ClassNameResponse]:
        """Читает страницу выбора класса теми же ограниченными read-правами."""
        try:
            response = await self._http_client.get(
                "/internal/classes",
                params={"limit": limit, "offset": offset},
                headers=self._headers,
                timeout=5.0,
                follow_redirects=False,
            )
            if response.status_code != 200:
                raise JournalUnavailableError
            rows = TypeAdapter(list[ClassNameResponse]).validate_json(response.content)
            if len(rows) > limit or len({row.id for row in rows}) != len(rows):
                raise JournalUnavailableError
            return rows
        except (httpx.HTTPError, ValidationError) as exc:
            raise JournalUnavailableError from exc


class AttendanceStatus(str, Enum):
    """Посещаемость урока; «не отмечено» — отсутствие строки."""

    PRESENT = "present"
    ABSENT_SICK = "absent_sick"
    ABSENT_EXCUSED = "absent_excused"
    ABSENT_UNEXCUSED = "absent_unexcused"


class GradeKind(str, Enum):
    """Тип оценки за урок из закрытого словаря."""

    ORAL = "oral"
    WRITTEN = "written"
    CONTROL = "control"


class DiaryAttendanceEntry(BaseModel):
    """Проверенная строка посещаемости из Journal."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    lesson_id: int = Field(strict=True, ge=1, le=2147483647)
    lesson_date: date
    class_id: int = Field(strict=True, ge=1, le=2147483647)
    student_id: UUID
    status: AttendanceStatus
    author_id: UUID
    generator: bool = Field(strict=True)
    created_at: AwareDatetime
    updated_at: AwareDatetime


class DiaryGradeEntry(BaseModel):
    """Проверенная строка оценки за урок из Journal."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    lesson_id: int = Field(strict=True, ge=1, le=2147483647)
    lesson_date: date
    class_id: int = Field(strict=True, ge=1, le=2147483647)
    subject_id: int = Field(strict=True, ge=1, le=2147483647)
    student_id: UUID
    grade: int = Field(strict=True, ge=2, le=5)
    kind: GradeKind
    author_id: UUID
    generator: bool = Field(strict=True)
    created_at: AwareDatetime
    updated_at: AwareDatetime


class DiaryEntriesResult(BaseModel):
    """Посещаемость и оценки окна дат, проверенные контрактом Journal."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    attendance: list[DiaryAttendanceEntry]
    grades: list[DiaryGradeEntry]


class DiaryAnchorResult(BaseModel):
    """Якорь дневника: дата последней записи и четверть опорной даты."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    last_entry_date: date | None
    quarter: int = Field(strict=True, ge=1, le=4)
    quarter_from: date
    quarter_to: date


class SubjectAverageEntry(BaseModel):
    """Средняя и четвертная оценка по одному предмету."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    subject_id: int = Field(strict=True, ge=1, le=2147483647)
    average: float = Field(strict=True, ge=2, le=5)
    grade_count: int = Field(strict=True, ge=1)
    quarter_grade: int = Field(strict=True, ge=2, le=5)


class LessonRecordValidationError(Exception):
    """Journal отверг данные записи урока; статус 422 проксируется."""


class LessonRecordConflictError(Exception):
    """Journal сообщил о конфликте учителя; статус 409 проксируется."""


class LessonContextBody(BaseModel):
    """Провалидированный Gateway'ем контекст урока в команде записи."""

    model_config = ConfigDict(extra="forbid")
    class_id: int = Field(ge=1, le=2147483647)
    subject_id: int = Field(ge=1, le=2147483647)
    lesson_date: date
    status: Literal["planned"]
    teacher_id: UUID


class AttendanceEntryBody(BaseModel):
    """Посещаемость одного ученика в пакете записи урока."""

    model_config = ConfigDict(extra="forbid")
    student_id: UUID
    status: AttendanceStatus


class GradeEntryBody(BaseModel):
    """Оценка одного ученика в пакете записи урока."""

    model_config = ConfigDict(extra="forbid")
    student_id: UUID
    kind: GradeKind
    grade: int = Field(ge=2, le=5)


class RecordLessonEntriesBody(BaseModel):
    """Тело команды записи урока без lesson_id (он в адресе)."""

    model_config = ConfigDict(extra="forbid")
    context: LessonContextBody
    attendance: list[AttendanceEntryBody] = Field(max_length=50)
    grades: list[GradeEntryBody] = Field(max_length=100)


class LessonRecordResult(DiaryEntriesResult):
    """Состояние записей урока после пакет-замены."""

    async def diary_anchor(
        self, student_id: UUID, reference: date | None = None
    ) -> DiaryAnchorResult:
        """Читает якорь дневника: последнюю запись и четверть опорной даты.

        Args:
            student_id: Ученик, чей якорь запрашивается.
            reference: Опорная дата четверти, если нужна именно она.

        Returns:
            Дата последней записи, номер и границы четверти.

        Raises:
            JournalUnavailableError: Сеть, статус или нарушение контракта.
        """
        params = {} if reference is None else {"reference": reference.isoformat()}
        try:
            response = await self._http_client.get(
                f"/internal/students/{student_id}/last-entry-date",
                params=params,
                headers=self._headers,
                timeout=5.0,
                follow_redirects=False,
            )
            if response.status_code != 200:
                raise JournalUnavailableError
            return DiaryAnchorResult.model_validate_json(response.content)
        except (httpx.HTTPError, ValidationError) as exc:
            raise JournalUnavailableError from exc

    async def list_student_entries(
        self,
        student_id: UUID,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        quarter: int | None = None,
    ) -> DiaryEntriesResult:
        """Читает записи ученика окном дат или номером четверти.

        Args:
            student_id: Ученик, чьи записи читаются.
            date_from: Начальная дата окна включительно.
            date_to: Конечная дата окна включительно.
            quarter: Номер четверти вместо дат окна.

        Returns:
            Посещаемость и оценки окна.

        Raises:
            JournalUnavailableError: Сеть, статус или нарушение контракта.
        """
        params: dict[str, str] = {}
        if quarter is not None:
            params["quarter"] = str(quarter)
        else:
            params["date_from"] = date_from.isoformat()
            params["date_to"] = date_to.isoformat()
        try:
            response = await self._http_client.get(
                f"/internal/students/{student_id}/diary-entries",
                params=params,
                headers=self._headers,
                timeout=5.0,
                follow_redirects=False,
            )
            if response.status_code != 200:
                raise JournalUnavailableError
            return DiaryEntriesResult.model_validate_json(response.content)
        except (httpx.HTTPError, ValidationError) as exc:
            raise JournalUnavailableError from exc

    async def subject_averages(
        self, student_id: UUID, quarter: int
    ) -> list[SubjectAverageEntry]:
        """Читает средние и четвертные оценки ученика за четверть.

        Args:
            student_id: Ученик, чьи средние читаются.
            quarter: Номер четверти от 1 до 4.

        Returns:
            Средняя, число оценок и четвертная по каждому предмету.

        Raises:
            JournalUnavailableError: Сеть, статус или нарушение контракта.
        """
        try:
            response = await self._http_client.get(
                f"/internal/students/{student_id}/subject-averages",
                params={"quarter": quarter},
                headers=self._headers,
                timeout=5.0,
                follow_redirects=False,
            )
            if response.status_code != 200:
                raise JournalUnavailableError
            return TypeAdapter(list[SubjectAverageEntry]).validate_json(
                response.content
            )
        except (httpx.HTTPError, ValidationError) as exc:
            raise JournalUnavailableError from exc

    async def lesson_entries(self, lesson_id: int) -> DiaryEntriesResult:
        """Читает записи одного урока для формы правки.

        Args:
            lesson_id: Урок, записи которого читаются.

        Returns:
            Посещаемость и оценки урока.

        Raises:
            JournalUnavailableError: Сеть, статус или нарушение контракта.
        """
        try:
            response = await self._http_client.get(
                f"/internal/lessons/{lesson_id}/entries",
                headers=self._headers,
                timeout=5.0,
                follow_redirects=False,
            )
            if response.status_code != 200:
                raise JournalUnavailableError
            return DiaryEntriesResult.model_validate_json(response.content)
        except (httpx.HTTPError, ValidationError) as exc:
            raise JournalUnavailableError from exc


class JournalWriteClient:
    """Клиент принципала записи уроков: заголовки учителя от Gateway."""

    def __init__(self, http_client: httpx.AsyncClient, service_token: str) -> None:
        """Хранит HTTP-пул и write-токен; заголовки учителя добавляет каждый запрос.

        Args:
            http_client: HTTP-клиент с базовым URL Journal.
            service_token: Bearer-токен принципала lesson-records:write.
        """
        self._http_client = http_client
        self._headers = {"Authorization": f"Bearer {service_token}"}

    async def record_lesson_entries(
        self, lesson_id: int, body: RecordLessonEntriesBody, teacher_id: UUID
    ) -> LessonRecordResult:
        """Заменяет записи урока пакетом учителя.

        Args:
            lesson_id: Урок Schedule, записи которого заменяются.
            body: Контекст урока, посещаемость и оценки пакета.
            teacher_id: UUID учителя из JWT, он же заголовок X-User-ID.

        Returns:
            Полное состояние записей урока после замены.

        Raises:
            LessonRecordValidationError: Journal вернул 422.
            LessonRecordConflictError: Journal вернул 409.
            JournalUnavailableError: Сеть, иной статус или нарушение контракта.
        """
        headers = {
            **self._headers,
            "X-User-ID": str(teacher_id),
            "X-User-Role": "teacher",
        }
        try:
            response = await self._http_client.post(
                f"/internal/lessons/{lesson_id}/entries",
                json=body.model_dump(mode="json"),
                headers=headers,
                timeout=5.0,
                follow_redirects=False,
            )
            if response.status_code == 422:
                raise LessonRecordValidationError
            if response.status_code == 409:
                raise LessonRecordConflictError
            if response.status_code != 200:
                raise JournalUnavailableError
            return LessonRecordResult.model_validate_json(response.content)
        except (httpx.HTTPError, ValidationError) as exc:
            raise JournalUnavailableError from exc
