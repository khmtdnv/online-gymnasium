"""Заранее создаёт счета по текущему составу классов из Journal."""

from datetime import date
from uuid import UUID

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter

from billing_service.storage import BillingStore
from billing_service.study_quarters import quarters_to_invoice


class JournalClass(BaseModel):
    """Проверенные данные класса на заданный учебный год."""

    model_config = ConfigDict(extra="forbid")
    id: int = Field(strict=True, gt=0)
    name: str
    study_year: int = Field(strict=True)
    created_at: AwareDatetime


class JournalPeriod(BaseModel):
    """Открытый период ученика из Journal."""

    model_config = ConfigDict(extra="forbid")
    id: int = Field(strict=True, gt=0)
    student_id: UUID
    class_id: int = Field(strict=True, gt=0)
    joined_at: AwareDatetime
    left_at: AwareDatetime | None


async def _pages(http: httpx.AsyncClient, path: str, token: str, model, **params):
    """Читает ограниченные страницы и отклоняет незавершённый обход."""
    adapter = TypeAdapter(list[model])
    for offset in range(0, 100_000, 100):
        response = await http.get(
            path,
            headers={"Authorization": f"Bearer {token}"},
            params={**params, "limit": 100, "offset": offset},
            timeout=10.0,
            follow_redirects=False,
        )
        response.raise_for_status()
        if len(response.content) > 1024 * 1024:
            raise ValueError("Journal response too large")
        rows = adapter.validate_json(response.content)
        if len(rows) > 100:
            raise ValueError("Journal page exceeds limit")
        yield rows
        if len(rows) < 100:
            return
    raise ValueError("Journal pagination limit exceeded")


async def issue_quarter_invoices(
    http: httpx.AsyncClient, token: str, store: BillingStore, today: date, price: int
) -> None:
    """Создаёт счета за текущую и следующую четверть для актуальных классов."""
    periods_by_year: dict[int, list[date]] = {}
    for start in quarters_to_invoice(today):
        year = start.year if start.month >= 9 else start.year - 1
        periods_by_year.setdefault(year, []).append(start)
    for year, starts in periods_by_year.items():
        seen_classes: set[int] = set()
        seen_students: set[UUID] = set()
        async for classes in _pages(
            http, "/internal/classes", token, JournalClass, study_year=year
        ):
            for school_class in classes:
                if school_class.study_year != year or school_class.id in seen_classes:
                    raise ValueError("Journal returned invalid or repeated class")
                seen_classes.add(school_class.id)
                async for periods in _pages(
                    http,
                    f"/internal/classes/{school_class.id}/current-periods",
                    token,
                    JournalPeriod,
                ):
                    for period in periods:
                        if (
                            period.class_id != school_class.id
                            or period.left_at is not None
                            or period.student_id in seen_students
                        ):
                            raise ValueError(
                                "Journal returned invalid or repeated student"
                            )
                        seen_students.add(period.student_id)
                        for start in starts:
                            await store.ensure_quarter_order(
                                period.student_id, start, price
                            )
