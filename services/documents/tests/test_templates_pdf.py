"""Четыре настоящих PDF из ограниченных локальных HTML-шаблонов."""

from pathlib import Path

from document_service.infrastructure.renderer import create_certificate_renderer


def test_all_templates_render_russian_educational_pdfs(tmp_path):
    renderer = create_certificate_renderer(Path(__file__).parents[1] / "templates")
    school = {
        "student_full_name": "Петров Иван <script>не HTML</script>",
        "class_name": "7А",
        "academic_year": "2026/2027",
    }
    for kind in ("certificate", "contract", "act", "receipt"):
        payload = (
            school | {"period_from": "2026-10-01", "period_to": "2026-10-31"}
            if kind == "act"
            else school
        )
        if kind == "receipt":
            payload = {
                "student_full_name": school["student_full_name"],
                "payment_id": 7,
                "study_month": "2026-10-01",
                "amount_kopecks": 300000,
                "currency": "RUB",
            }
        pdf = renderer.render_document(kind, payload)
        assert pdf.startswith(b"%PDF") and len(pdf) > 3000
        (tmp_path / f"{kind}.pdf").write_bytes(pdf)
