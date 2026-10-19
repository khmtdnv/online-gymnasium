from pathlib import Path

from jinja2 import Environment, FileSystemLoader, Template, select_autoescape
from weasyprint import HTML

from document_service.domain.certificate import CertificateData


class WeasyPrintCertificateRenderer:
    """Заполняет HTML-шаблон через Jinja2 и строит PDF через WeasyPrint."""

    def __init__(self, template: Template) -> None:
        """Сохраняет зависимости и настройки компонента.

        Args:
            template: Подготовленный HTML-шаблон Jinja2 для справки.
        """
        self._template = template

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
    return WeasyPrintCertificateRenderer(template)
