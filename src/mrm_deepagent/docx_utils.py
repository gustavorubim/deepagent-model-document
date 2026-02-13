"""DOCX traversal helpers with paragraph/table ordering."""

from __future__ import annotations

from collections.abc import Iterator

from docx.document import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph


def iter_block_items(parent: DocxDocument | _Cell) -> Iterator[Paragraph | Table]:
    """Yield paragraphs and tables in original document order."""
    if isinstance(parent, DocxDocument):
        parent_elm = parent.element.body
    elif isinstance(parent, _Cell):
        parent_elm = parent._tc
    else:
        raise TypeError(f"Unsupported parent type: {type(parent)!r}")

    for child in parent_elm.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, parent)
        elif isinstance(child, CT_Tbl):
            yield Table(child, parent)


def iter_table_paragraphs(table: Table) -> Iterator[Paragraph]:
    """Yield all table cell paragraphs."""
    for row in table.rows:
        for cell in row.cells:
            yield from cell.paragraphs


def table_to_text(table: Table) -> str:
    """Flatten table rows into readable text lines."""
    lines: list[str] = []
    for row in table.rows:
        values = [cell.text.strip() for cell in row.cells]
        cleaned = [value for value in values if value]
        if cleaned:
            lines.append(" | ".join(cleaned))
    return "\n".join(lines)
