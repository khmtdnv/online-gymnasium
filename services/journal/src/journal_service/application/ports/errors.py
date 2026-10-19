class ApplicationException(Exception):
    """Общая основа ожидаемых ошибок приложения Journal."""


class TeacherAlreadyAssignedError(ApplicationException):
    """Уникальная пара преподаватель—класс уже существует."""


class TeacherNotFoundError(ApplicationException):
    """Gateway подтвердил отсутствие назначаемого преподавателя."""


class InvalidTeacherError(ApplicationException):
    """Назначаемый пользователь не является активным преподавателем."""


class CurrentPeriodAlreadyExistsError(ApplicationException):
    """Другая транзакция уже создала открытый период ученика."""


class StudentNotFoundError(ApplicationException):
    """Gateway подтвердил, что пользователя с указанным ID нет."""


class InvalidStudentError(ApplicationException):
    """Пользователь не является активным учеником."""


class StudentClassConflictError(ApplicationException):
    """Ученик уже состоит в другом классе; добавление не выполняет перевод."""


class StudentClassPeriodConflictError(ApplicationException):
    """Ожидаемый исходный период отсутствует, уже закрыт или изменился."""


class InvalidAddStudentDataError(ApplicationException):
    """ID класса, ученика, инициатора или запроса недопустим."""


class UserLookupUnavailableError(ApplicationException):
    """Gateway недоступен или вернул недостоверные данные пользователя."""


class DuplicateClassError(ApplicationException):
    """Класс с таким именем уже существует в указанном учебном году."""


class InvalidClassDataError(ApplicationException):
    """Данные создания класса или параметры списка нарушают правила приложения."""


class CurrentPeriodNotFoundError(ApplicationException):
    """У ученика нет открытого периода нахождения в классе."""


class ClassNotFoundError(ApplicationException):
    """Класс с указанным ID не существует в Journal."""


class InvalidClassPeriodQueryError(ApplicationException):
    """ID или параметры страницы периодов нарушают контракт чтения."""
