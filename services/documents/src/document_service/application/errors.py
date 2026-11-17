class ApplicatinError(Exception):
    """Базовая ошибка сценария приложения."""


class TemporaryStorageError(ApplicatinError):
    """Загрузка документа не удалась из-за ошибки сети или сервера хранилища."""


class PermanentDocumentError(ApplicatinError):
    """Данные документа не позволяют завершить генерацию повторной попыткой."""
