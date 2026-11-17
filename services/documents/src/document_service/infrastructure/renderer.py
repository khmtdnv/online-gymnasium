from pathlib import Path

from jinja2 import Environment, FileSystemLoader, Template, select_autoescape
from weasyprint import HTML

from document_service.domain.certificate import CertificateData


class WeasyPrintCertificateRenderer:
    """Заполняет HTML-шаблон через Jinja2 и строит PDF через WeasyPrint."""

    def __init__(
        self, template: Template, environment: Environment | None = None
    ) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            template: Подготовленный HTML-шаблон Jinja2 для справки.
        """
        self._template = template
        self._environment = environment

    def render_document(self, document_type: str, payload: dict) -> bytes:
        """Заполняет только разрешённый локальный шаблон, без URL из данных.

        Args:
            document_type: Один из четырёх поддерживаемых учебных шаблонов.
            payload: Проверенный снимок данных на момент создания задания.

        Returns:
            Байты PDF с маркировкой учебного документа.
        """
        names = {
            "certificate": "educational_certificate.html",
            "contract": "contract.html",
            "act": "act.html",
            "receipt": "receipt.html",
        }
        if document_type not in names or self._environment is None:
            raise ValueError("Unsupported document template")
        template = self._environment.get_template(names[document_type])
        content = template.render(**payload)

        def no_external_resources(url, *args, **kwargs):
            # В этих шаблонах нет внешних изображений/стилей и удалённых шрифтов.
            raise ValueError("External PDF resources are disabled")

        return HTML(string=content, url_fetcher=no_external_resources).write_pdf()

    def render(self, certificate: CertificateData) -> bytes:
        """Заполняет шаблон данными справки и строит PDF.

        Args:
            certificate: Проверенные данные справки об обучении.

        Returns:
            Байты готового PDF.
        """
        rendered_template = self._template.render(
            student_full_name=certificate.student_full_name,
            class_name=certificate.class_name,
            academic_year=certificate.academic_year,
        )

        return HTML(string=rendered_template).write_pdf()


def create_certificate_renderer(
    template_directory: Path,
) -> WeasyPrintCertificateRenderer:
    """Загружает шаблон certificate.html с экранированием HTML.

    Args:
        template_directory: Каталог, содержащий certificate.html.

    Returns:
        Генератор справок с подготовленным шаблоном.
    """
    environment = Environment(
        loader=FileSystemLoader(template_directory),
        autoescape=select_autoescape(["html"]),
    )
    template = environment.get_template("certificate.html")
    return WeasyPrintCertificateRenderer(template, environment)
