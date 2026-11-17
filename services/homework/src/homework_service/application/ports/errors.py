"""Значимые ошибки сценариев, без зависимости от SQLAlchemy и httpx."""


class HomeworkAlreadyExistsError(Exception):
    """Для урока уже сохранено общее домашнее задание."""


class OwnerLookupUnavailableError(Exception):
    """Владелец данных недоступен или нарушил ожидаемый контракт ответа."""


class LessonNotFoundError(Exception):
    """Указанный урок не существует в Schedule."""


class HomeworkAccessDeniedError(Exception):
    """Преподавателю недоступен урок или больше нет назначения классу."""


class InvalidHomeworkDataError(Exception):
    """Выбранный срок не соответствует уроку или текущему времени."""


class HomeworkNotFoundError(Exception):
    """Задание отсутствует или недоступно в текущем классе ученика."""


class HomeworkFileNotReadyError(Exception):
    """Ожидаемое вложение существует, но его байты ещё не готовы к скачиванию."""


class HomeworkAnswerConflictError(Exception):
    """Попытка/проверка уже существует или закрыта; повтор не совпал с исходным."""


class HomeworkAnswerNotFoundError(HomeworkNotFoundError):
    """Ответ или его вложение отсутствуют либо недоступны пользователю."""
