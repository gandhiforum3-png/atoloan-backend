"""
Structural validation test for the rate sheet parser.

Parses AMERICAN FIRST CU.md and asserts that key top-level sections
(credit_union_info with a name) are present in the result.

Requires OPENAI_API_KEY; skipped when absent.
"""
import os
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).parents[2]

pytestmark = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set",
)


def test_rate_sheet_parser_validation():
    """Parse AMERICAN FIRST CU.md and verify required fields are present."""
    from app.services.rate_sheet_parser import parse_rate_sheet_from_markdown

    markdown_file = APP_ROOT / "upload_pdf" / "AMERICAN FIRST CU.md"
    if not markdown_file.exists():
        pytest.skip(f"Test markdown file not found: {markdown_file}")

    markdown_text = markdown_file.read_text()
    result = parse_rate_sheet_from_markdown(markdown_text)

    assert result is not None, "Parser returned None"
    assert result.credit_union_info is not None, "Missing credit_union_info"
    assert result.credit_union_info.name, "credit_union_info.name is empty"

    if result.loan_programs:
        print(f"\n{len(result.loan_programs)} loan programs found")
        for program in result.loan_programs[:3]:
            print(f"  • {program.program_name}")
