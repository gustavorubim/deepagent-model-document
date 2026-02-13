from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document


def build_template_docx(
    path: Path,
    duplicate_fill_id: bool = False,
    include_table: bool = False,
    include_untagged_heading: bool = False,
) -> Path:
    document = Document()
    document.add_heading("[FILL][ID:exec_summary] Executive Summary", level=1)
    document.add_paragraph(
        "Summarize model objective and business impact. [[SECTION_CONTENT]] "
        "[[CHECK:model_validated]]"
    )
    if include_table:
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "Model validated"
        table.cell(0, 1).text = "[[CHECK:model_validated]]"
        table.cell(1, 0).text = "Validation owner"
        table.cell(1, 1).text = "Model Risk Team"

    document.add_heading("[FILL][ID:data_description] Data Description", level=1)
    document.add_paragraph("Describe training data sources and quality checks. [[SECTION_CONTENT]]")

    if duplicate_fill_id:
        document.add_heading("[FILL][ID:data_description] Duplicate ID", level=1)
        document.add_paragraph("Duplicate section to force validation failure.")

    if include_untagged_heading:
        document.add_heading("4. Model Change Management", level=1)
        document.add_paragraph("Untagged heading should be treated as a fillable section.")

    document.add_heading("[SKIP][ID:validator_notes] Validator Notes", level=1)
    document.add_paragraph("This section is for validator-only completion.")

    document.add_heading("[VALIDATOR][ID:validation_results] Validation Results", level=1)
    document.add_paragraph("Completed by model validation team.")

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


@pytest.fixture
def untagged_template_path(tmp_path: Path) -> Path:
    return build_template_docx(tmp_path / "untagged_template.docx", include_untagged_heading=True)
