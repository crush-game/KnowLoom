from app.knowloom.services.title_normalizer import normalize_document_title
from app.knowloom.services.file_ingest import metadata_from_dict


def test_title_normalizer_matches_revised_versions():
    assert normalize_document_title("《研究生细则（2025年修订）》.pdf") == normalize_document_title("研究生细则.docx")


def test_file_job_metadata_ignores_non_document_fields():
    metadata=metadata_from_dict({"doc_key":"rules","title":"办法","glossary":[{"name":"x"}]})
    assert metadata.doc_key == "rules"
    assert metadata.title == "办法"
