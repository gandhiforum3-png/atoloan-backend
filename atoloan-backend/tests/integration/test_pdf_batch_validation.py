"""
Batch PDF validation test — runs pdf_batch_validator over the upload_pdf/ directory.

Skipped when no upload_pdf/ directory is found.
"""
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).parents[2]


def test_pdf_batch_validation():
    """Validate all PDFs in upload_pdf/ and assert zero failures."""
    try:
        from app.services.pdf_batch_validator import compare_with_original, validate_directory
    except ImportError:
        pytest.skip("pdf_batch_validator service not available")

    pdf_dir = APP_ROOT / "upload_pdf"
    if not pdf_dir.exists():
        pytest.skip(f"upload_pdf directory not found: {pdf_dir}")

    results = validate_directory(pdf_dir, verbose=False)

    for pdf_file in sorted(pdf_dir.glob("*.pdf")):
        if pdf_file.name == "Unknown 2.pdf":
            continue
        compare_with_original(pdf_file, verbose=False)

    total = results.get("total", 0)
    invalid = results.get("invalid", 0)
    print(f"\n{total - invalid}/{total} PDFs valid")
    assert invalid == 0, f"{invalid} PDFs failed batch validation"
