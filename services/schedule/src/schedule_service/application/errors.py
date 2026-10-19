class ApplicationException(Exception):
    """Базовая ошибка сценария приложения."""


class ScheduleConflict(ApplicationException):
    """Урок нарушает ограничения расписания в базе данных."""


class LessonNotFound(ApplicationException):
    """Урок с указанным ID не найден."""


class VersionConflict(ApplicationException):
    """Версия урока изменилась с момента чтения клиентом."""


class IdempotencyKeyReuse(ApplicationException):
    """Ключ повторного запроса уже использован с другими данными."""


class IdempotencyKeyAlreadyExists(ApplicationException):
    """Другой запрос уже зарезервировал этот ключ операции."""


class ScheduleCacheBusy(ApplicationException):
    """Не удалось получить согласованное расписание за лимит попыток."""
