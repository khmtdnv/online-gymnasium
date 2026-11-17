"""Настоящий API ЮKassa, ограниченный подтверждённым тестовым магазином."""

from decimal import Decimal
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import ValidationError

from billing_service.contracts import (
    PaymentSnapshot,
    ProviderPayment,
    ProviderRefund,
    RefundSnapshot,
    ShopInfo,
)


class ProviderUnavailableError(Exception):
    """Ответ не подтверждён сетью или не соответствует нашему тестовому заказу."""


class RefundNotAllowedError(Exception):
    """Платёж не оплачен, уже возвращён или допускает только частичный возврат."""


def check_confirmation_url(value: str) -> str:
    """Не позволяет браузеру уйти на посторонний сайт по повреждённому ответу."""
    url = urlsplit(value)
    host = url.hostname or ""
    if (
        url.scheme != "https"
        or url.username
        or url.password
        or url.port not in {None, 443}
        or not any(
            host == domain or host.endswith("." + domain)
            for domain in ("yoomoney.ru", "yookassa.ru")
        )
    ):
        raise ValueError("Unexpected payment confirmation URL")
    return value


class YooKassaClient:
    """Использует Basic только на фиксированном HTTPS API провайдера."""

    def __init__(
        self, client: httpx.AsyncClient, shop_id: str, secret_key: str, return_url: str
    ) -> None:
        self._client = client
        self._shop_id = shop_id
        self._auth = httpx.BasicAuth(shop_id, secret_key)
        self._return_url = return_url

    async def _request(
        self,
        method: str,
        path: str,
        *,
        key: UUID | None = None,
        body: dict | None = None,
    ):
        try:
            response = await self._client.request(
                method,
                "https://api.yookassa.ru/v3" + path,
                auth=self._auth,
                headers={"Idempotence-Key": str(key)} if key else {},
                json=body,
                timeout=httpx.Timeout(15, connect=5),
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError from exc
        if response.status_code != 200 or len(response.content) > 1048576:
            raise ProviderUnavailableError
        return response.content

    async def check_test_shop(self) -> None:
        """До мутации требует авторитетные test=true, account_id и enabled."""
        try:
            shop = ShopInfo.model_validate_json(await self._request("GET", "/me"))
            if (
                shop.account_id != self._shop_id
                or not shop.test
                or shop.status != "enabled"
            ):
                raise ProviderUnavailableError
        except ValidationError as exc:
            raise ProviderUnavailableError from exc

    def _payment(self, content: bytes, snapshot: PaymentSnapshot) -> ProviderPayment:
        try:
            value = ProviderPayment.model_validate_json(content)
            if (
                not value.test
                or value.recipient.account_id != self._shop_id
                or value.amount.kopecks != snapshot.amount_kopecks
                or value.metadata.get("order_id") != str(snapshot.order_id)
                or value.metadata.get("payment_id") != str(snapshot.id)
                or (
                    snapshot.provider_id is not None
                    and value.id != snapshot.provider_id
                )
                or (value.status == "succeeded") != value.paid
            ):
                raise ValueError("Payment does not match order")
            if value.confirmation:
                check_confirmation_url(value.confirmation.confirmation_url)
            if value.status == "pending" and value.confirmation is None:
                raise ValueError("Pending payment has no confirmation")
            if (
                value.refunded_amount
                and value.refunded_amount.kopecks > snapshot.amount_kopecks
            ):
                raise ValueError("Invalid refunded amount")
            return value
        except (ValidationError, ValueError) as exc:
            raise ProviderUnavailableError from exc

    async def create_payment(self, snapshot: PaymentSnapshot) -> ProviderPayment:
        """Повторяет неизменную сумму/metadata/key, не получает карту от клиента."""
        await self.check_test_shop()
        body = {
            "amount": {
                "value": f"{Decimal(snapshot.amount_kopecks) / 100:.2f}",
                "currency": "RUB",
            },
            "capture": True,
            "confirmation": {"type": "redirect", "return_url": self._return_url},
            "description": f"Учебная оплата обучения, заказ {snapshot.order_id}",
            "metadata": {
                "order_id": str(snapshot.order_id),
                "payment_id": str(snapshot.id),
            },
            "save_payment_method": False,
        }
        return self._payment(
            await self._request(
                "POST", "/payments", key=snapshot.provider_key, body=body
            ),
            snapshot,
        )

    async def get_payment(self, snapshot: PaymentSnapshot) -> ProviderPayment:
        """Проверяет весь сохранённый контракт, а не только status webhook."""
        if snapshot.provider_id is None:
            raise ProviderUnavailableError
        return self._payment(
            await self._request("GET", f"/payments/{snapshot.provider_id}"), snapshot
        )

    def _refund(self, content: bytes, snapshot: RefundSnapshot) -> ProviderRefund:
        try:
            result = ProviderRefund.model_validate_json(content)
            if (
                result.payment_id != snapshot.payment.provider_id
                or result.amount.kopecks != snapshot.payment.amount_kopecks
                or (
                    snapshot.provider_id is not None
                    and result.id != snapshot.provider_id
                )
            ):
                raise ValueError("Refund does not match payment")
            return result
        except (ValidationError, ValueError) as exc:
            raise ProviderUnavailableError from exc

    async def create_refund(self, snapshot: RefundSnapshot) -> ProviderRefund:
        """Проверяет исходный test-payment перед полным возвратом с отдельнымkey."""
        await self.check_test_shop()
        payment = await self.get_payment(snapshot.payment)
        # После потерянного ACK этот же возврат уже мог завершиться. Нельзя
        # запрещать повтор прежнего ключа только из-за refundable=False.
        # Право первой попытки проверяется сценарием до локального резерва.
        if payment.status != "succeeded":
            raise RefundNotAllowedError
        body = {
            "payment_id": str(payment.id),
            "amount": {
                "value": f"{Decimal(snapshot.payment.amount_kopecks) / 100:.2f}",
                "currency": "RUB",
            },
            "description": f"Учебный полный возврат {snapshot.id}",
        }
        return self._refund(
            await self._request(
                "POST", "/refunds", key=snapshot.provider_key, body=body
            ),
            snapshot,
        )

    async def get_refund(self, snapshot: RefundSnapshot) -> ProviderRefund:
        """Сверяет возврат после чтения принадлежащего нашемуtestshop платежа."""
        if snapshot.provider_id is None:
            raise ProviderUnavailableError
        await self.get_payment(snapshot.payment)
        return self._refund(
            await self._request("GET", f"/refunds/{snapshot.provider_id}"), snapshot
        )
