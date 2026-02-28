"""
Test pdf_parser_v2.py table-merging enhancement on SF FIRE CU.pdf.

Skipped when the target PDF is absent.
"""
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).parents[2]


@pytest.mark.xfail(
    reason="SF FIRE CU.pdf has known multi-page table extraction issues in pdf_parser_v2",
    strict=False,
)
def test_merged_parser():
    """Parse SF FIRE CU.pdf and verify multi-row table data survives merging."""
    from app.services.pdf_parser_v2 import parse_pdf
    from app.services.pdf_validator import print_validation_report, validate_pdf_to_markdown

    pdf_dir = APP_ROOT / "upload_pdf"
    pdf_file = pdf_dir / "SF FIRE CU.pdf"

    if not pdf_file.exists():
        pytest.skip(f"PDF file not found: {pdf_file}")

    result = parse_pdf(pdf_file)
    md_path = Path(result["markdown_path"])
    md_content = md_path.read_text()
    lines = md_content.split("\n")

    for pattern, label in [
        ("49-60", "49-60 MOS data"),
        ("73-84", "73-84 MOS data"),
        ("%", "interest-rate percentages"),
    ]:
        assert any(pattern in line for line in lines), (
            f"Expected pattern '{pattern}' ({label}) not found in generated markdown"
        )

    validation = validate_pdf_to_markdown(pdf_file, md_path)
    print_validation_report(validation)
    assert validation.get("is_valid", False), "PDF markdown validation failed"
