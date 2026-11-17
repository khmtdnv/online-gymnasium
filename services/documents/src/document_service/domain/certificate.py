from dataclasses import dataclass


class InvalidCertificateData(Exception):
    """Поля справки не являются непустыми строками."""


@dataclass(frozen=True, slots=True)
class CertificateData:
    """Данные справки об обучении с обязательными непустыми полями."""

    student_full_name: str
    class_name: str
    academic_year: str

    def __post_init__(self) -> None:
        """Проверяет строковые типы и непустоту полей, не изменяя их значения.

        Raises:
            InvalidCertificateData: Имя, класс или учебный год не являются
                непустыми строками.
        """
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (self.student_full_name, self.class_name, self.academic_year)
        ):
            raise InvalidCertificateData
