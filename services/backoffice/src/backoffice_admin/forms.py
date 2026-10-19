"""Формы проверки входных данных административных команд."""

from django import forms

from backoffice_admin.journal_client import JournalClass


class CreateUserForm(forms.Form):
    """Проверяет данные для создания пользователя через Gateway."""

    email = forms.EmailField(label="Email")
    last_name = forms.CharField(label="Фамилия", max_length=100)
    first_name = forms.CharField(label="Имя", max_length=100)
    middle_name = forms.CharField(label="Отчество", max_length=100, required=False)
    password = forms.CharField(widget=forms.PasswordInput, strip=False)
    role = forms.ChoiceField(
        choices=(
            ("student", "Ученик"),
            ("teacher", "Учитель"),
            ("parent", "Родитель"),
            ("admin", "Администратор"),
        )
    )

    def clean_password(self) -> str:
        """Отклоняет пробельный пароль, не меняя непустое исходное значение.

        Returns:
            Введённый пароль, включая крайние пробелы.

        Raises:
            forms.ValidationError: Пароль состоит только из пробелов.
        """
        password = self.cleaned_data["password"]
        if not password.strip():
            raise forms.ValidationError("Пароль не должен состоять только из пробелов.")
        return password


class LinkParentStudentForm(forms.Form):
    """Проверяет UUID для привязки родителя к ученику.

    Существование пользователей и соответствие их ролей проверяет Gateway.
    """

    parent_id = forms.UUIDField(label="ID родителя")
    student_id = forms.UUIDField(label="ID ученика")


class AddStudentToClassForm(forms.Form):
    """Проверяет UUID ученика и выбор класса из актуального ответа Journal."""

    student_id = forms.UUIDField(label="Ученик", widget=forms.HiddenInput)
    class_id = forms.TypedChoiceField(label="Класс", coerce=int)

    def __init__(self, *args, classes: list[JournalClass], **kwargs) -> None:
        """Заполняет варианты отдельно для каждого экземпляра формы.

        Args:
            *args: Стандартные позиционные аргументы Django-формы.
            classes: Проверенные классы, полученные через API Journal.
            **kwargs: Стандартные именованные аргументы Django-формы.
        """
        super().__init__(*args, **kwargs)
        self.fields["class_id"].choices = [("", "Выберите класс")] + [
            (
                school_class.id,
                f"{school_class.name} · {school_class.study_year}/{school_class.study_year + 1}",
            )
            for school_class in classes
        ]


class UserSearchForm(forms.Form):
    """Ограничивает запрос до обращения к Gateway."""

    q = forms.CharField(label="ФИО или email", min_length=2, max_length=200)


class TeacherClassForm(forms.Form):
    """Проверяет пару назначения; снятие не требует доступного списка классов."""

    teacher_id = forms.UUIDField(widget=forms.HiddenInput)
    class_id = forms.TypedChoiceField(label="Класс", coerce=int)
    action = forms.ChoiceField(
        choices=(("assign", "Назначить"), ("remove", "Снять")), widget=forms.HiddenInput
    )

    def __init__(self, *args, classes: list[JournalClass], **kwargs) -> None:
        """Назначение разрешает только актуальный выбор, снятие — заданную пару.

        Args:
            *args: Стандартные аргументы формы Django.
            classes: Доступные классы для назначения.
            **kwargs: Стандартные настройки формы.
        """
        super().__init__(*args, **kwargs)
        self.fields["class_id"].choices = [("", "Выберите класс")] + [
            (x.id, f"{x.name} · {x.study_year}/{x.study_year + 1}") for x in classes
        ]
        if self.is_bound and self.data.get("action") == "remove":
            value = self.data.get("class_id", "")
            self.fields["class_id"].choices = [(value, "Снять назначение")]

    def clean_class_id(self) -> int:
        """Ограничивает ID для обоих действий.

        Returns:
            Положительный PostgreSQL integer.

        Raises:
            forms.ValidationError: Значение вне диапазона integer.
        """
        value = self.cleaned_data["class_id"]
        if not 1 <= value <= 2147483647:
            raise forms.ValidationError("Некорректный ID класса.")
        return value


class ChangeStudentClassForm(forms.Form):
    """Сохраняет ожидаемый период формы и требует подтверждения завершения."""

    operation = forms.ChoiceField(
        label="Действие",
        choices=(
            ("transfer", "Перевести в другой класс"),
            ("end", "Завершить пребывание в классе"),
        ),
    )
    expected_period_id = forms.IntegerField(
        min_value=1, max_value=2147483647, widget=forms.HiddenInput
    )
    target_class_id = forms.TypedChoiceField(
        label="Новый класс", coerce=int, required=False
    )
    confirm_end = forms.BooleanField(
        label="Подтверждаю завершение пребывания без назначения нового класса",
        required=False,
    )

    def __init__(self, *args, classes: list[JournalClass], **kwargs) -> None:
        """Заполняет варианты; завершение не зависит от доступности списка классов.

        Args:
            *args: Стандартные аргументы формы, включая исходный POST.
            classes: Проверенный список классов Journal.
            **kwargs: Стандартные настройки, включая initial только для GET.
        """
        super().__init__(*args, **kwargs)
        self.fields["target_class_id"].choices = [("", "Выберите класс")] + [
            (item.id, f"{item.name} · {item.study_year}/{item.study_year + 1}")
            for item in classes
        ]
        if self.is_bound and self.data.get("operation") == "end":
            self.fields["target_class_id"].disabled = True

    def clean(self):
        """Проверяет поля, относящиеся к выбранной операции.

        Returns:
            Проверенные данные без требования целевого класса при завершении.
        """
        cleaned = super().clean()
        if cleaned.get("operation") == "transfer" and not cleaned.get(
            "target_class_id"
        ):
            self.add_error("target_class_id", "Выберите новый класс.")
        if cleaned.get("operation") == "end" and not cleaned.get("confirm_end"):
            self.add_error("confirm_end", "Подтвердите завершение пребывания в классе.")
        return cleaned


class UpdateUserNameForm(forms.Form):
    """Проверяет новое ФИО; отчество не обязательно, имена не уникальны."""

    last_name = forms.CharField(label="Фамилия", max_length=100)
    first_name = forms.CharField(label="Имя", max_length=100)
    middle_name = forms.CharField(label="Отчество", max_length=100, required=False)
