from celery import Celery

from document_service.config import DocumentSettings


def create_celery_app(settings: DocumentSettings) -> Celery:
    """Создаёт приложение Celery с настроенным брокером RabbitMQ.

    Args:
        settings: Настройки текущего сервиса.

    Returns:
        Приложение Celery без отдельного хранилища результатов.
    """
    return Celery("document_service", broker=settings.celery_broker_url)
