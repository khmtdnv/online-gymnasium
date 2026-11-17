"""Закрытый HTTP-клиент Billing; JWT пользователя сюда не пересылается."""

from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, StrictBool, TypeAdapter, ValidationError

from gateway_service.application.billing import BillingConfig, Payment, TuitionOrder


class BillingRequestError(Exception):
    """Известный отказ Billing или недостоверный ответ владельца данных."""

    def __init__(self, status: int = 503):
        self.status = status


class QuarterAccess(BaseModel):
    """Строгий ответ Billing для проверки учебного доступа."""

    model_config = ConfigDict(extra="forbid")
    allowed: StrictBool


class BillingClient:
    """Проверяет формы ответа, границы страниц и принадлежность результата."""

    def __init__(self, http: httpx.AsyncClient, token: str):
        self.http = http
        self.headers = {"Authorization": f"Bearer {token}"}

    async def _request(self, method, path, contract, *, body=None, params=None):
        try:
            response = await self.http.request(
                method,
                path,
                headers=self.headers,
                json=body,
                params=params,
                timeout=60.0,
                follow_redirects=False,
            )
            if response.status_code not in {200, 202}:
                # Не доверяем произвольному тексту/коду чужого сервиса.
                known = {404: "payment_not_found", 409: "billing_conflict"}
                status = response.status_code
                if status in known and response.json() == {"code": known[status]}:
                    raise BillingRequestError(status)
                raise BillingRequestError
            if len(response.content) > 1024 * 1024:
                raise BillingRequestError
            return TypeAdapter(contract).validate_json(response.content)
        except (httpx.HTTPError, ValidationError, ValueError) as exc:
            raise BillingRequestError from exc

    async def config(self) -> BillingConfig:
        """Читает только готовность настройки и серверную цену, не credentials."""
        return await self._request("GET", "/internal/config", BillingConfig)

    async def quarter_access(self, student_id: UUID) -> bool:
        """Не принимает строки или числа вместо настоящего boolean."""
        result = await self._request(
            "GET", f"/internal/students/{student_id}/quarter-access", QuarterAccess
        )
        return result.allowed

    async def orders(
        self, student_id: UUID, limit: int, offset: int
    ) -> list[TuitionOrder]:
        """Читает ограниченную страницу именно указанного ученика."""
        rows = await self._request(
            "GET",
            "/internal/orders",
            list[TuitionOrder],
            params={"student_id": str(student_id), "limit": limit, "offset": offset},
        )
        if len(rows) > limit or any(row.student_id != student_id for row in rows):
            raise BillingRequestError
        return rows

    async def payments(self, limit: int, offset: int) -> list[Payment]:
        """Читает административную страницу; публичные права проверяет Gateway API."""
        rows = await self._request(
            "GET",
            "/internal/payments",
            list[Payment],
            params={"limit": limit, "offset": offset},
        )
        if len(rows) > limit:
            raise BillingRequestError
        return rows

    async def get_payment(self, payment_id: int) -> Payment:
        """Проверяет совпадение числового ID, а не только корректность JSON."""
        row = await self._request("GET", f"/internal/payments/{payment_id}", Payment)
        if row.id != payment_id:
            raise BillingRequestError
        return row

    async def start(self, body: dict) -> Payment:
        """Не позволяет ответу изменить ученика, плательщика или выбранный месяц."""
        row = await self._request("POST", "/internal/payments", Payment, body=body)
        if (
            str(row.student_id) != body["student_id"]
            or str(row.payer_id) != body["payer_id"]
            or row.study_month.isoformat() != body["study_month"]
            or row.period_type != body.get("period_type", "month")
        ):
            raise BillingRequestError
        return row

    async def _change(
        self, payment_id: int, action: str, body: dict | None = None
    ) -> Payment:
        row = await self._request(
            "POST", f"/internal/payments/{payment_id}/{action}", Payment, body=body
        )
        if row.id != payment_id:
            raise BillingRequestError
        return row

    async def refresh(self, payment_id: int) -> Payment:
        """Просит владельца сверить платёж, не выставляет статус в Gateway."""
        return await self._change(payment_id, "refresh")

    async def refund(self, payment_id: int, body: dict) -> Payment:
        """Передаёт отдельный постоянный ключ полного возврата и UUID admin."""
        return await self._change(payment_id, "refund", body)

    async def reconcile(self, payment_id: int, body: dict) -> Payment:
        """Инициирует авторитетный GET провайдера по административной команде."""
        return await self._change(payment_id, "reconcile", body)

    async def webhook(self, body: dict) -> dict[str, bool]:
        """Передаёт только вид сигнала и ID объекта, без недоверенного статуса."""
        return await self._request(
            "POST", "/internal/webhook", dict[str, bool], body=body
        )
