import PyPDF2
import io


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """
    Takes raw PDF bytes and returns extracted text as a string.
    """
    reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"
    return text.strip()


def extract_text_from_txt(file_bytes: bytes) -> str:
    """
    Takes raw text file bytes and returns the decoded string.
    """
    return file_bytes.decode("utf-8").strip()
