"""Контракт чтения и изменения периодов нахождения учеников в классах."""

from typing import Protocol
from uuid import UUID

from journal_service.domain.student_class_period import StudentClassPeriod


class StudentClassPeriodRepository(Protocol):
    """Предоставляет текущие периоды, историю ученика и состав класса."""

    async def create_period(self, period: StudentClassPeriod) -> StudentClassPeriod:
        """Создаёт открытый период с ID и временем, назначенными базой.

        Args:
            period: Ученик и класс; joined_at при переводе содержит серверную
                дату закрытия исходного периода, иначе назначается базой.

        Returns:
            Сохранённый открытый период с серверными полями.

        Raises:
            CurrentPeriodAlreadyExistsError: Открытый период ученика уже существует.
        """
        ...

    async def get_period_for_update(
        self, student_id: UUID, period_id: int
    ) -> StudentClassPeriod | None:
        """Блокирует конкретный период, в том числе закрытый, до конца UoW.

        Args:
            student_id: Владелец периода из команды.
            period_id: Ожидаемый ID из исходной формы.

        Returns:
            Актуальный период с указанными student_id и period_id либо None
            при отсутствии этой пары. Закрытый период также возвращается.
        """
        ...

    async def close_period(self, period_id: int) -> StudentClassPeriod | None:
        """Однократно закрывает открытый период без самостоятельного commit.

        Args:
            period_id: ID периода после проверки владельца обработчиком.

        Returns:
            Закрытый период с текущим серверным left_at либо None,
            если период отсутствует или уже закрыт.
        """
        ...

    async def get_current_period_for_student(
        self, student_id: UUID
    ) -> StudentClassPeriod | None:
        """Получает открытый период ученика, не возвращая завершённую историю.

        Args:
            student_id: ID ученика из Gateway.

        Returns:
            Текущий период либо None, если ученик сейчас не состоит в классе.
        """
        ...

    async def list_periods_for_student(
        self, student_id: UUID, limit: int, offset: int
    ) -> list[StudentClassPeriod]:
        """Получает страницу истории ученика, включая текущий период.

        Args:
            student_id: ID ученика из Gateway.
            limit: Максимальное число периодов в ответе.
            offset: Число пропускаемых периодов.

        Returns:
            Периоды по возрастанию joined_at, затем ID; пустой список, если
            записей на странице нет.
        """
        ...

    async def list_current_periods_for_class(
        self, class_id: int, limit: int, offset: int
    ) -> list[StudentClassPeriod]:
        """Получает страницу открытых периодов учеников указанного класса.

        Args:
            class_id: ID школьного класса в Journal.
            limit: Максимальное число периодов в ответе.
            offset: Число пропускаемых открытых периодов.

        Returns:
            Текущий состав по возрастанию ID периода; пустой список, если
            записей на странице нет.
        """
        ...
