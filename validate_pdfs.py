#!/usr/bin/env python3
"""
Quick start example for the improved PDF parser and validator.

Run this script to:
1. Parse all PDFs in upload_pdf directory
2. Validate the generated markdown
3. Generate a summary report
"""

import sys
from pathlib import Path

# Add app to path
app_root = Path(__file__).parent
sys.path.insert(0, str(app_root))

from app.services.pdf_batch_validator import validate_directory, compare_with_original


def main():
    """Run validation on all PDFs."""
    pdf_dir = app_root / "upload_pdf"
    
    if not pdf_dir.exists():
        print(f"Error: {pdf_dir} not found")
        return 1
    
    print("\n" + "="*70)
    print("PDF PARSER & VALIDATOR - QUICK START")
    print("="*70)
    
    # Validate all PDFs
    print("\nValidating all PDFs in:", pdf_dir)
    results = validate_directory(pdf_dir, verbose=False)
    
    # Additional comparison
    print("\n" + "="*70)
    print("DETAILED COMPARISON")
    print("="*70)
    
    for pdf_file in sorted(pdf_dir.glob("*.pdf")):
        if pdf_file.name == "Unknown 2.pdf":
            continue  # Skip test files
        
        comparison = compare_with_original(pdf_file, verbose=True)
        if comparison:
            print()
    
    return 0 if results["invalid"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
