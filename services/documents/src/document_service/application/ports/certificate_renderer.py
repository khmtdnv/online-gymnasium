from typing import Protocol

from document_service.domain.certificate import CertificateData


class CertificateRenderer(Protocol):
    """Контракт преобразования данных справки в байты PDF."""

    def render(self, certificate: CertificateData) -> bytes:
        """Заполняет шаблон данными справки и строит PDF.

        Args:
            certificate: Проверенные данные справки об обучении.

        Returns:
            Байты готового PDF.
        """
        ...
