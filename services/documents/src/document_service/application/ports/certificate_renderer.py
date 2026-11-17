from typing import Protocol

from document_service.domain.certificate import CertificateData


class CertificateRenderer(Protocol):
    """Контракт преобразования данных справки в байты PDF."""

    def render_document(self, document_type: str, payload: dict) -> bytes:
        """Строит новый учебный PDF по разрешённому типу и проверенному снимку."""
        ...

    def render(self, certificate: CertificateData) -> bytes:
        """Заполняет шаблон данными справки и строит PDF.

        Args:
            certificate: Проверенные данные справки об обучении.

        Returns:
            Байты готового PDF.
        """
        ...
