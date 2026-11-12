"""
Live test for the rate sheet parser: sends AMERICAN FIRST CU.pdf to Claude and
checks the structured result. Requires ANTHROPIC_API_KEY and the sample PDF;
skipped when either is absent.
"""
import asyncio
import os
import time
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).parents[2]

pytestmark = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)


def test_rate_sheet_parser():
    from app.services.rate_sheet_parser import parse_rate_sheet_pdf

    pdf_file = APP_ROOT / "upload_pdf" / "AMERICAN FIRST CU.pdf"
    if not pdf_file.exists():
        pytest.skip(f"Test PDF not found: {pdf_file}")

    start = time.time()
    result = asyncio.run(parse_rate_sheet_pdf(pdf_file.read_bytes()))
    print(f"\nParsed in {time.time() - start:.1f}s")

    assert result.credit_union_info is not None, "Missing credit_union_info"
    assert result.credit_union_info.name, "credit_union_info.name is empty"
    assert result.loan_programs, "No loan programs extracted"
    for program in result.loan_programs[:3]:
        print(f"  • {program.program_name}")
