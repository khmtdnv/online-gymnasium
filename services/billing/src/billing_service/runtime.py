"""Создание зависимостей HTTP и worker без побочных сетевых запросов при импорте."""

from billing_service.provider import YooKassaClient
from billing_service.service import BillingService
from billing_service.storage import BillingStore


def create_service(settings, http_client, sessions) -> BillingService:
    """Не создаёт фиктивного провайдера, если test-shop ключи ещё не заполнены."""
    secret = settings.yookassa_secret_key.get_secret_value()
    provider = (
        YooKassaClient(
            http_client,
            settings.yookassa_shop_id,
            secret,
            settings.public_origin.rstrip("/") + "/billing",
        )
        if settings.yookassa_shop_id and secret
        else None
    )
    return BillingService(
        BillingStore(sessions),
        provider,
        settings.tuition_price_kopecks,
        settings.quarter_price_kopecks,
    )
