# """
# Batch validation utility for PDF parsing.

# Run validation on all PDF files in a directory to ensure consistent
# and accurate conversion to markdown.
# """

# from __future__ import annotations

# import logging
# from pathlib import Path
# from typing import Optional

# from app.services.pdf_parser_v2 import parse_pdf
# from app.services.pdf_validator import validate_pdf_to_markdown, print_validation_report


# def configure_logging(verbose: bool = False) -> None:
#     """Configure logging for the validation process."""
#     level = logging.DEBUG if verbose else logging.INFO
#     logging.basicConfig(
#         level=level,
#         format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
#     )


# def validate_pdf_file(
#     pdf_path: Path,
#     force_reparse: bool = False,
#     print_report: bool = True
# ) -> dict:
#     """
#     Validate a single PDF file.
    
#     Args:
#         pdf_path: Path to PDF file
#         force_reparse: If True, regenerate markdown even if it exists
#         print_report: If True, print validation report
        
#     Returns:
#         Validation result dictionary
#     """
#     md_path = pdf_path.with_suffix(".md")
    
#     # Parse PDF if needed
#     if force_reparse or not md_path.exists():
#         logging.info(f"Parsing {pdf_path.name}...")
#         parse_pdf(pdf_path)
    
#     # Validate
#     logging.info(f"Validating {pdf_path.name}...")
#     result = validate_pdf_to_markdown(pdf_path, md_path)
    
#     if print_report:
#         print_validation_report(result)
    
#     return result


# def validate_directory(
#     directory: Path,
#     pattern: str = "*.pdf",
#     force_reparse: bool = False,
#     verbose: bool = False
# ) -> dict:
#     """
#     Validate all PDF files in a directory.
    
#     Args:
#         directory: Directory containing PDFs
#         pattern: Glob pattern for PDF files
#         force_reparse: If True, regenerate all markdown files
#         verbose: If True, enable verbose logging
        
#     Returns:
#         Summary of validation results
#     """
#     configure_logging(verbose)
    
#     pdf_files = sorted(directory.glob(pattern))
#     if not pdf_files:
#         logging.warning(f"No PDF files found in {directory}")
#         return {"total": 0, "valid": 0, "invalid": 0, "files": []}
    
#     logging.info(f"Found {len(pdf_files)} PDF files to validate\n")
    
#     results = {
#         "total": len(pdf_files),
#         "valid": 0,
#         "invalid": 0,
#         "files": [],
#         "summary_by_status": {"valid": [], "invalid": []},
#     }
    
#     for pdf_path in pdf_files:
#         logging.info(f"\n{'='*70}")
#         result = validate_pdf_file(pdf_path, force_reparse, print_report=True)
        
#         file_result = {
#             "path": str(pdf_path),
#             "name": pdf_path.name,
#             "is_valid": result["is_valid"],
#             "similarity": result["text_similarity"],
#             "error_count": len(result["errors"]),
#             "warning_count": len(result["warnings"]),
#         }
        
#         results["files"].append(file_result)
        
#         if result["is_valid"]:
#             results["valid"] += 1
#             results["summary_by_status"]["valid"].append(pdf_path.name)
#         else:
#             results["invalid"] += 1
#             results["summary_by_status"]["invalid"].append(pdf_path.name)
    
#     # Print summary
#     print(f"\n\n{'='*70}")
#     print("VALIDATION SUMMARY")
#     print(f"{'='*70}")
#     print(f"Total files: {results['total']}")
#     print(f"Valid: {results['valid']} ({results['valid']/max(1, results['total'])*100:.1f}%)")
#     print(f"Invalid: {results['invalid']}")
    
#     if results["summary_by_status"]["valid"]:
#         print(f"\n✓ Valid files ({len(results['summary_by_status']['valid'])}):")
#         for name in results["summary_by_status"]["valid"]:
#             print(f"  - {name}")
    
#     if results["summary_by_status"]["invalid"]:
#         print(f"\n✗ Invalid files ({len(results['summary_by_status']['invalid'])}):")
#         for name in results["summary_by_status"]["invalid"]:
#             print(f"  - {name}")
    
#     return results


# def compare_with_original(
#     pdf_path: Path,
#     verbose: bool = False
# ) -> Optional[dict]:
#     """
#     Compare newly generated markdown with any existing version.
    
#     Args:
#         pdf_path: Path to PDF file
#         verbose: If True, print detailed diff
        
#     Returns:
#         Comparison result or None
#     """
#     from app.services.pdf_validator import extract_pdf_content, extract_markdown_content
    
#     configure_logging(verbose)
    
#     md_path = pdf_path.with_suffix(".md")
#     if not md_path.exists():
#         logging.error(f"Markdown file not found: {md_path}")
#         return None
    
#     pdf_content = extract_pdf_content(pdf_path)
#     md_content = extract_markdown_content(md_path)
    
#     comparison = {
#         "pdf_word_count": pdf_content["word_count"],
#         "md_word_count": md_content["word_count"],
#         "pdf_percentage_count": len(set(pdf_content["percentages"])),
#         "md_percentage_count": len(set(md_content["percentages"])),
#         "pdf_numeric_count": len(set(pdf_content["numeric_values"])),
#         "md_numeric_count": len(set(md_content["numeric_values"])),
#         "pdf_table_count": len(pdf_content["tables"]),
#         "md_table_count": len(md_content["tables"]),
#     }
    
#     if verbose:
#         print(f"\nComparison: {pdf_path.name}")
#         print(f"  Word count:      PDF={comparison['pdf_word_count']}, MD={comparison['md_word_count']}")
#         print(f"  Percentages:     PDF={comparison['pdf_percentage_count']}, MD={comparison['md_percentage_count']}")
#         print(f"  Numeric values:  PDF={comparison['pdf_numeric_count']}, MD={comparison['md_numeric_count']}")
#         print(f"  Tables:          PDF={comparison['pdf_table_count']}, MD={comparison['md_table_count']}")
    
#     return comparison


# if __name__ == "__main__":
#     import sys
    
#     # Example usage
#     if len(sys.argv) > 1:
#         pdf_dir = Path(sys.argv[1])
#     else:
#         # Default to upload_pdf directory
#         pdf_dir = Path(__file__).parent.parent.parent / "upload_pdf"
    
#     validate_directory(pdf_dir, verbose=True)
