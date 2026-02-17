#!/usr/bin/env python3
"""Test the merged pdf_parser_v2.py with table merging enhancements."""

import sys
from pathlib import Path

# Add app to path
app_dir = Path(__file__).parent / "atoloan-backend"
sys.path.insert(0, str(app_dir))

from app.services.pdf_parser_v2 import parse_pdf
from app.services.pdf_validator import validate_pdf_to_markdown, print_validation_report

def test_merged_parser():
    """Test the merged parser on SF FIRE CU PDF."""
    pdf_dir = app_dir / "upload_pdf"
    pdf_file = pdf_dir / "SF FIRE CU.pdf"
    
    if not pdf_file.exists():
        print(f"ERROR: PDF file not found: {pdf_file}")
        return False
    
    print(f"\n{'='*70}")
    print(f"Testing merged parser on: {pdf_file.name}")
    print(f"{'='*70}\n")
    
    # Parse the PDF
    result = parse_pdf(pdf_file)
    md_path = Path(result["markdown_path"])
    
    print(f"✓ PDF parsed successfully")
    print(f"  Output: {md_path}")
    
    # Read generated markdown
    md_content = md_path.read_text()
    print(f"  Generated markdown size: {len(md_content)} chars")
    
    # Check for table rows with rate data
    lines = md_content.split('\n')
    table_rows = [l for l in lines if l.startswith('|')]
    print(f"  Table rows in markdown: {len(table_rows)}")
    
    # Look for key rate data
    checks = [
        ('49-60', '49-60 MOS data'),
        ('73-84', '73-84 MOS data'),
        ('%', 'Interest rate percentages'),
    ]
    
    for pattern, label in checks:
        found = any(pattern in line for line in lines)
        status = "✓" if found else "✗"
        print(f"  {status} {label}: {pattern}")
    
    # Validate against original PDF
    print(f"\n  Running validation against original PDF...")
    validation = validate_pdf_to_markdown(pdf_file, md_path)
    print_validation_report(validation)
    
    return validation.get("is_valid", False)

if __name__ == "__main__":
    success = test_merged_parser()
    sys.exit(0 if success else 1)
