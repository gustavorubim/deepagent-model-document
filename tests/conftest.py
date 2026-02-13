from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document


def build_template_docx(
    path: Path, duplicate_fill_id: bool = False, include_table: bool = False
) -> Path:
    document = Document()
    document.add_heading("[FILL][ID:exec_summary] Executive Summary", level=1)
    document.add_paragraph(
        "Summarize model objective and business impact. [[CHECK:model_validated]]"
    )

    document.add_heading("[FILL][ID:data_description] Data Description", level=1)
    document.add_paragraph("Describe training data sources and quality checks.")

    if duplicate_fill_id:
        document.add_heading("[FILL][ID:data_description] Duplicate ID", level=1)
        document.add_paragraph("Duplicate section to force validation failure.")

    document.add_heading("[SKIP][ID:validator_notes] Validator Notes", level=1)
    document.add_paragraph("This section is for validator-only completion.")

    document.add_heading("[VALIDATOR][ID:validation_results] Validation Results", level=1)
    document.add_paragraph("Completed by model validation team.")

    if include_table:
        table = document.add_table(rows=1, cols=1)
        table.cell(0, 0).text = "Unsupported table payload."

    path.parent.mkdir(parents=True, exist_ok=True)
    document.save(path)
    return path


@pytest.fixture
def template_path(tmp_path: Path) -> Path:
    return build_template_docx(tmp_path / "template.docx")


@pytest.fixture
def duplicate_template_path(tmp_path: Path) -> Path:
    return build_template_docx(tmp_path / "duplicate_template.docx", duplicate_fill_id=True)


@pytest.fixture
def table_template_path(tmp_path: Path) -> Path:
    return build_template_docx(tmp_path / "table_template.docx", include_table=True)
