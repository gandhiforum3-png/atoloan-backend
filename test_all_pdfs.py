#!/usr/bin/env python3
"""Test the merged pdf_parser_v2.py on all PDFs."""

import sys
from pathlib import Path

# Add app to path
app_dir = Path(__file__).parent / "atoloan-backend"
sys.path.insert(0, str(app_dir))

from app.services.pdf_parser_v2 import parse_pdf
from app.services.pdf_validator import validate_pdf_to_markdown

def test_all_pdfs():
    """Test the merged parser on all PDFs."""
    pdf_dir = app_dir / "upload_pdf"
    pdf_files = sorted([f for f in pdf_dir.glob("*.pdf")])
    
    if not pdf_files:
        print(f"ERROR: No PDF files found in {pdf_dir}")
        return False
    
    print(f"\n{'='*70}")
    print(f"Testing merged parser on {len(pdf_files)} PDFs")
    print(f"{'='*70}\n")
    
    results = []
    all_valid = True
    
    for pdf_file in pdf_files:
        try:
            # Parse the PDF
            result = parse_pdf(pdf_file)
            md_path = Path(result["markdown_path"])
            
            # Validate
            validation = validate_pdf_to_markdown(pdf_file, md_path)
            is_valid = validation.get("is_valid", False)
            similarity = validation.get("similarity_percentage", 0)
            
            status = "✓" if is_valid else "✗"
            results.append({
                "file": pdf_file.name,
                "status": status,
                "similarity": f"{similarity:.1f}%",
                "valid": is_valid,
            })
            
            if not is_valid:
                all_valid = False
                
        except Exception as e:
            results.append({
                "file": pdf_file.name,
                "status": "✗",
                "similarity": "N/A",
                "valid": False,
                "error": str(e)
            })
            all_valid = False
    
    # Print summary
    print(f"Results:\n")
    for r in results:
        error_msg = f" - {r.get('error', '')}" if 'error' in r else ""
        print(f"  {r['status']} {r['file']:<35} {r['similarity']:>6} similarity{error_msg}")
    
    passed = sum(1 for r in results if r["valid"])
    print(f"\n  {'='*60}")
    print(f"  {passed}/{len(results)} PDFs passed validation")
    print(f"  {'='*60}\n")
    
    return all_valid

if __name__ == "__main__":
    success = test_all_pdfs()
    sys.exit(0 if success else 1)
