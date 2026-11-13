"""Read and normalize source data."""
import re
import unicodedata
from pathlib import Path

from pypdf import PdfReader

from .models import DocumentPage

MIN_CHARS = 50  # pages shorter than this are logged as empty/too short and skipped


def normalize_text(text: str) -> str:
    """NFC Unicode, drop soft hyphens, re-join hyphenated words, collapse spaces, keep line breaks."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("­", "")                    # soft hyphen
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)          # word broken across lines
    text = re.sub(r"[ \t ]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_pdf(path: Path, document_id: str, source: str,
             pages_wanted: set[int] | None = None,
             metadata: dict | None = None,
             errors: list[dict] | None = None) -> list[DocumentPage]:
    """Extract each physical page (1-based), keep source/page, log empty or failing pages."""
    errors = errors if errors is not None else []
    reader = PdfReader(str(path))
    result = []
    for number, page in enumerate(reader.pages, start=1):
        if pages_wanted and number not in pages_wanted:
            continue
        try:
            text = normalize_text(page.extract_text() or "")
        except Exception as exc:  # log the failure; never silently skip
            errors.append({"document_id": document_id, "page": number,
                           "reason": f"extract_error: {exc}"})
            continue
        if len(text) < MIN_CHARS:
            errors.append({"document_id": document_id, "page": number,
                           "reason": "empty_or_too_short", "chars": len(text)})
            continue
        result.append(DocumentPage(document_id, source, number, text, dict(metadata or {})))
    if pages_wanted:
        missing = sorted(pages_wanted - set(range(1, len(reader.pages) + 1)))
        for number in missing:
            errors.append({"document_id": document_id, "page": number,
                           "reason": "page_not_in_pdf"})
    return result
