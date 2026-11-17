"""Служебный Bearer не заменяет проверку создателя конкретного PDF."""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from document_service.domain.document import DocumentJob, DocumentStatus
from tests.test_documents_api import FakeDocumentRepository, create_test_app


def test_private_template_routes_reject_public_and_foreign_reads():
    creator = uuid4()
    job = DocumentJob(
        uuid4(),
        "contract",
        DocumentStatus.COMPLETED,
        {},
        "documents/test.pdf",
        None,
        datetime.now(UTC),
        creator_id=creator,
    )
    repository = FakeDocumentRepository()
    repository.jobs[job.id] = job
    app = create_test_app(repository)
    app.state.settings.gateway_service_token = "docs-test-only"
    with TestClient(app) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get(f"/documents/{job.id}/content").status_code == 401
        assert client.get(f"/internal/documents/{job.id}").status_code == 401
        headers = {"Authorization": "Bearer docs-test-only", "X-Actor-ID": str(uuid4())}
        assert (
            client.get(f"/internal/documents/{job.id}", headers=headers).status_code
            == 404
        )
        assert (
            client.get(
                f"/internal/documents/{job.id}/content", headers=headers
            ).status_code
            == 404
        )
        headers["X-Actor-ID"] = str(creator)
        response = client.get(f"/internal/documents/{job.id}", headers=headers)
        assert response.status_code == 200
        assert response.json()["document_type"] == "contract"
        assert "payload" not in response.json()
        assert response.headers["cache-control"] == "private, no-store"
        assert client.get(
            f"/internal/documents/{job.id}/content", headers=headers
        ).content.startswith(b"%PDF")
