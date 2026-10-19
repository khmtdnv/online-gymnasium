"""Значимые ошибки сценариев, без зависимости от SQLAlchemy и httpx."""


class HomeworkAlreadyExistsError(Exception):
    """Для урока уже сохранено общее домашнее задание."""


class OwnerLookupUnavailableError(Exception):
    """Владелец данных недоступен или нарушил ожидаемый контракт ответа."""


class LessonNotFoundError(Exception):
    """Указанный урок не существует в Schedule."""


class HomeworkAccessDeniedError(Exception):
    """Учитель не вправе выдавать ДЗ из этого урока."""


class InvalidHomeworkDataError(Exception):
    """Выбранный срок не соответствует уроку или текущему времени."""


class HomeworkNotFoundError(Exception):
    """Задание отсутствует или недоступно в текущем классе ученика."""
