"""Fixed-size and structure-aware chunking. Chunks never cross page boundaries."""
import re

from .models import Chunk, DocumentPage


def _chunk(page: DocumentPage, idx: int, text: str, method: str) -> Chunk:
    return Chunk(
        chunk_id=f"{page.document_id}:p{page.page:04d}:c{idx:03d}",
        document_id=page.document_id,
        source=page.source,
        page=page.page,
        text=text,
        metadata={**page.metadata, "chunk_method": method},
    )


def fixed_size(page: DocumentPage, size: int, overlap: int) -> list[Chunk]:
    """Strategy A: sliding character window of `size` with `overlap`."""
    if not 0 <= overlap < size:
        raise ValueError("overlap must be in [0, size)")
    text, step, chunks = page.text, size - overlap, []
    for start in range(0, len(text), step):
        piece = text[start:start + size].strip()
        if piece:
            chunks.append(_chunk(page, len(chunks), piece, f"fixed{size}/{overlap}"))
        if start + size >= len(text):
            break
    return chunks


def _paragraphs(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(parts) > 1:
        return [re.sub(r"\s*\n\s*", " ", p) for p in parts]
    # pypdf rarely keeps blank lines: join lines and break after a line ending a sentence.
    # Heading lines (no final punctuation) stick to the paragraph after them.
    paras, buf = [], []
    for line in (l.strip() for l in text.split("\n")):
        if not line:
            continue
        buf.append(line)
        if re.search(r"[.!?:;]$", line):
            paras.append(" ".join(buf))
            buf = []
    if buf:
        paras.append(" ".join(buf))
    return paras


def _split_long(paragraph: str, max_size: int) -> list[str]:
    """Split an oversized paragraph on sentence ends; hard-cut sentences longer than max_size."""
    out, cur = [], ""
    for s in re.split(r"(?<=[.!?])\s+", paragraph):
        while len(s) > max_size:
            out.append(s[:max_size])
            s = s[max_size:]
        if cur and len(cur) + 1 + len(s) > max_size:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        out.append(cur)
    return out


def by_paragraph(page: DocumentPage, max_size: int) -> list[Chunk]:
    """Strategy B: group whole paragraphs up to max_size characters."""
    pieces = []
    for p in _paragraphs(page.text):
        pieces.extend(_split_long(p, max_size) if len(p) > max_size else [p])
    chunks, cur = [], ""
    for p in pieces:
        if cur and len(cur) + 1 + len(p) > max_size:
            chunks.append(_chunk(page, len(chunks), cur, f"paragraph{max_size}"))
            cur = p
        else:
            cur = f"{cur}\n{p}".strip()
    if cur:
        chunks.append(_chunk(page, len(chunks), cur, f"paragraph{max_size}"))
    return chunks
