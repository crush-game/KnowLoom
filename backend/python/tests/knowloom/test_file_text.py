from io import BytesIO
from zipfile import ZipFile
from app.knowloom.services.file_text import extract_file_text

def test_reads_markdown_and_docx_text():
    assert extract_file_text("rule.md", "# 办法\n第十二条".encode()) == "# 办法\n第十二条"
    data=BytesIO()
    with ZipFile(data, "w") as z: z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>第十二条</w:t></w:r></w:p></w:body></w:document>')
    assert extract_file_text("rule.docx", data.getvalue()) == "第十二条"
