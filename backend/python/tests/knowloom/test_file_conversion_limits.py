import pytest
from app.knowloom.services.file_text import FileTooLarge, MAX_UPLOAD_BYTES, convert_file

def test_rejects_file_larger_than_twenty_mb():
    with pytest.raises(FileTooLarge):
        convert_file("large.md", b"x" * (MAX_UPLOAD_BYTES + 1))
