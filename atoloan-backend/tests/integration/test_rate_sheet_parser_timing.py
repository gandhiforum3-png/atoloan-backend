"""
Timing test for the rate sheet parser.

Requires OPENAI_API_KEY and the AMERICAN FIRST CU.md markdown file;
skipped automatically when either is absent.
"""
import os
import time
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).parents[2]

pytestmark = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set",
)


def test_rate_sheet_parser_timing():
    """Parse AMERICAN FIRST CU.md and report wall-clock time."""
    from app.services.rate_sheet_parser import parse_rate_sheet_from_markdown

    markdown_file = APP_ROOT / "upload_pdf" / "AMERICAN FIRST CU.md"
    if not markdown_file.exists():
        pytest.skip(f"Test file not found: {markdown_file}")

    markdown_text = markdown_file.read_text()
    assert markdown_text, "Markdown file is empty"

    start = time.time()
    result = parse_rate_sheet_from_markdown(markdown_text)
    elapsed = time.time() - start

    print(f"\nParser completed in {elapsed:.2f}s")
    assert result is not None, "Parser returned None"
    if result.credit_union_info:
        print(f"Credit Union: {result.credit_union_info.name}")
