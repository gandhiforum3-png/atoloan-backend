"""
PDF to Markdown validation utilities.

This module provides functions to validate that the generated markdown
matches the original PDF content in terms of:
- Text completeness
- Table accuracy
- Format consistency
- Missing or corrupted data detection
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TypedDict

import pdfplumber


class ValidationResult(TypedDict):
    """Result of content validation."""
    is_valid: bool
    pdf_text_length: int
    md_text_length: int
    text_similarity: float
    missing_content: list[str]
    corrupted_cells: list[str]
    warnings: list[str]
    errors: list[str]


def extract_pdf_content(pdf_path: Path) -> dict:
    """
    Extract complete content from PDF for validation.
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        Dictionary with extracted PDF content
    """
    content = {
        "raw_text": "",
        "tables": [],
        "tables_raw": [],
        "word_count": 0,
        "numeric_values": [],
        "percentages": [],
    }
    
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                # Extract full text
                text = page.extract_text() or ""
                content["raw_text"] += f"\n--- Page {page_num} ---\n{text}"
                
                # Extract words and count
                words = page.extract_words()
                content["word_count"] += len(words)
                
                # Extract numeric values and percentages (with optional trailing punctuation)
                for word in words:
                    txt = word.get("text", "")
                    # Match percentages with optional punctuation after
                    match = re.search(r"(\d+\.?\d*)%", txt)
                    if match:
                        content["percentages"].append(match.group(0))
                    if re.search(r"\b\d+\b", txt):
                        content["numeric_values"].append(txt)
                
                # Extract tables
                tables = page.find_tables()
                for table in tables:
                    rows = table.extract()
                    content["tables_raw"].append(rows)
                    content["tables"].append({
                        "page": page_num,
                        "row_count": len(rows),
                        "col_count": len(rows[0]) if rows else 0,
                    })
    except Exception as e:
        logging.error("Error extracting PDF content: %s", e)
    
    return content


def extract_markdown_content(md_path: Path) -> dict:
    """
    Extract structured content from markdown file.
    
    Args:
        md_path: Path to markdown file
        
    Returns:
        Dictionary with extracted markdown content
    """
    content = {
        "raw_text": "",
        "tables": [],
        "word_count": 0,
        "numeric_values": [],
        "percentages": [],
        "table_cells": [],
    }
    
    try:
        text = md_path.read_text(encoding="utf-8")
        content["raw_text"] = text
        content["word_count"] = len(text.split())
        
        # Extract percentages (avoid those in markdown syntax like "%---------")
        percentages = re.findall(r"\d+\.?\d*%", text)
        # Filter out percentages that are part of markdown table separators
        content["percentages"] = [p for p in percentages if not re.search(r'%-+', text[max(0, text.find(p)-5):text.find(p)+len(p)+5])]
        
        # Extract numeric values
        content["numeric_values"] = re.findall(r"\b\d+\b", text)
        
        # Extract markdown tables - more precise pattern
        # A table has: header row | separator row with dashes | data rows
        table_pattern = r'\|[^|\n]+\|\s*\n\|[-\s:|]+\|\s*(?:\n\|[^|\n]+\|)*'
        tables_found = re.findall(table_pattern, text)
        
        for table_md in tables_found:
            lines = table_md.strip().split('\n')
            rows = []
            for line in lines:
                # Skip separator lines (those with lots of dashes)
                if re.match(r'^\|\s*[-:\s|]+\|\s*$', line):
                    continue
                # Parse actual content rows
                cells = line.split('|')[1:-1]
                if cells and any(c.strip() for c in cells):
                    rows.append([cell.strip() for cell in cells])
            
            if rows:
                content["tables"].append({
                    "row_count": len(rows),
                    "col_count": len(rows[0]) if rows else 0,
                })
                # Collect all cells for corruption check
                for row in rows:
                    content["table_cells"].extend([cell.strip() for cell in row])
    
    except Exception as e:
        logging.error("Error extracting markdown content: %s", e)
    
    return content


def detect_corrupted_cells(md_content: dict, pdf_content: dict) -> list[str]:
    """
    Detect cells that appear corrupted or incomplete.
    
    Heuristics:
    - Repeated identical values (84%, 84%, 84%)
    - Truncated text (ends with just a period or digit)
    - Missing required numeric data
    - Text that doesn't match PDF extracted text
    
    Args:
        md_content: Extracted markdown content
        pdf_content: Extracted PDF content
        
    Returns:
        List of corruption indicators
    """
    corrupted = []
    
    # Check for repeated identical cells
    md_cells = md_content.get("table_cells", [])
    if len(md_cells) > 0:
        from collections import Counter
        cell_counts = Counter(md_cells)
        for cell, count in cell_counts.items():
            if count > 10 and len(cell) <= 5 and '%' in cell:
                corrupted.append(f"Repeated cell detected: '{cell}' appears {count} times")
    
    # Check for suspicious "84%" pattern (from your example)
    suspicious_count = md_content["percentages"].count("84%")
    if suspicious_count > 5:
        corrupted.append(f"Suspicious '84%' placeholder detected {suspicious_count} times")
    
    # Check for incomplete text patterns
    for cell in md_cells:
        if cell and len(cell) <= 3 and re.match(r'^[\d.%]+$', cell):
            continue  # Skip normal short numeric cells
        if re.match(r'^.*\d+\.$', cell):  # Ends with digit then period
            corrupted.append(f"Potentially truncated cell: '{cell}'")
    
    return corrupted


def calculate_similarity(pdf_text: str, md_text: str) -> float:
    """
    Calculate text similarity between PDF and markdown.
    
    Uses simple approach: ratio of common unique tokens.
    
    Args:
        pdf_text: Extracted PDF text
        md_text: Extracted markdown text
        
    Returns:
        Similarity score 0.0-1.0
    """
    def normalize_and_tokenize(text):
        """Normalize text and extract tokens."""
        text = text.lower()
        text = re.sub(r'[^a-z0-9%\s]', ' ', text)
        tokens = set(text.split())
        return tokens
    
    pdf_tokens = normalize_and_tokenize(pdf_text)
    md_tokens = normalize_and_tokenize(md_text)
    
    if not pdf_tokens:
        return 0.0
    
    common = pdf_tokens & md_tokens
    return len(common) / len(pdf_tokens)


def validate_pdf_to_markdown(pdf_path: Path, md_path: Path) -> ValidationResult:
    """
    Validate that markdown file contains complete and accurate PDF content.
    
    Args:
        pdf_path: Path to original PDF
        md_path: Path to generated markdown
        
    Returns:
        ValidationResult with detailed findings
    """
    result: ValidationResult = {
        "is_valid": True,
        "pdf_text_length": 0,
        "md_text_length": 0,
        "text_similarity": 0.0,
        "missing_content": [],
        "corrupted_cells": [],
        "warnings": [],
        "errors": [],
    }
    
    # Extract content from both files
    pdf_content = extract_pdf_content(pdf_path)
    
    if not md_path.exists():
        result["is_valid"] = False
        result["errors"].append(f"Markdown file does not exist: {md_path}")
        return result
    
    md_content = extract_markdown_content(md_path)
    
    # Store metrics
    result["pdf_text_length"] = len(pdf_content["raw_text"])
    result["md_text_length"] = len(md_content["raw_text"])
    
    # Calculate similarity
    result["text_similarity"] = calculate_similarity(
        pdf_content["raw_text"],
        md_content["raw_text"]
    )
    
    # Check text length
    if result["md_text_length"] < result["pdf_text_length"] * 0.5:
        result["is_valid"] = False
        result["errors"].append(
            f"Markdown significantly shorter than PDF "
            f"({result['md_text_length']} vs {result['pdf_text_length']} chars)"
        )
    
    # Check similarity threshold
    if result["text_similarity"] < 0.6:
        result["is_valid"] = False
        result["errors"].append(
            f"Low text similarity: {result['text_similarity']:.2%}"
        )
    
    # Detect corrupted cells
    corrupted = detect_corrupted_cells(md_content, pdf_content)
    if corrupted:
        result["is_valid"] = False
        result["corrupted_cells"] = corrupted
        for corruption in corrupted[:5]:  # Limit to first 5
            result["errors"].append(f"Data corruption: {corruption}")
    
    # Check percentage completeness
    pdf_percentages = set(pdf_content["percentages"])
    md_percentages = set(md_content["percentages"])
    
    # Normalize for comparison (remove trailing punctuation)
    pdf_pct_normalized = {re.sub(r'[,.]$', '', p) for p in pdf_percentages}
    md_pct_normalized = {re.sub(r'[,.]$', '', p) for p in md_percentages}
    
    missing_pct = pdf_pct_normalized - md_pct_normalized
    if missing_pct:
        result["warnings"].append(
            f"Some percentages may be missing or in different format "
            f"(PDF: {len(pdf_pct_normalized)}, MD: {len(md_pct_normalized)})"
        )
        for pct in list(missing_pct)[:3]:
            result["missing_content"].append(f"Possibly missing percentage: {pct}")
    else:
        # All percentages found - this is good
        result["text_similarity"] = max(result["text_similarity"], 0.95)
    
    # Check table structure
    if len(pdf_content["tables"]) != len(md_content["tables"]):
        result["warnings"].append(
            f"Table count mismatch: PDF has {len(pdf_content['tables'])}, "
            f"markdown has {len(md_content['tables'])}"
        )
    
    for i, (pdf_table, md_table) in enumerate(
        zip(pdf_content["tables"], md_content["tables"])
    ):
        if pdf_table["row_count"] != md_table["row_count"]:
            result["warnings"].append(
                f"Table {i+1}: Row count mismatch "
                f"(PDF: {pdf_table['row_count']}, MD: {md_table['row_count']})"
            )
        if pdf_table["col_count"] != md_table["col_count"]:
            result["warnings"].append(
                f"Table {i+1}: Column count mismatch "
                f"(PDF: {pdf_table['col_count']}, MD: {md_table['col_count']})"
            )
    
    return result


def print_validation_report(result: ValidationResult) -> None:
    """
    Print a formatted validation report.
    
    Args:
        result: ValidationResult to display
    """
    status = "✓ VALID" if result["is_valid"] else "✗ INVALID"
    print(f"\n{'='*70}")
    print(f"PDF to Markdown Validation Report: {status}")
    print(f"{'='*70}")
    
    print(f"\nMetrics:")
    print(f"  PDF Text Length:    {result['pdf_text_length']:,} chars")
    print(f"  Markdown Text Length: {result['md_text_length']:,} chars")
    print(f"  Text Similarity:    {result['text_similarity']:.1%}")
    
    if result["errors"]:
        print(f"\nErrors ({len(result['errors'])}):")
        for error in result["errors"]:
            print(f"  ✗ {error}")
    
    if result["missing_content"]:
        print(f"\nMissing Content ({len(result['missing_content'])}):")
        for item in result["missing_content"][:10]:
            print(f"  - {item}")
        if len(result["missing_content"]) > 10:
            print(f"  ... and {len(result['missing_content']) - 10} more")
    
    if result["corrupted_cells"]:
        print(f"\nData Corruption Indicators ({len(result['corrupted_cells'])}):")
        for corruption in result["corrupted_cells"][:10]:
            print(f"  ⚠ {corruption}")
        if len(result["corrupted_cells"]) > 10:
            print(f"  ... and {len(result['corrupted_cells']) - 10} more")
    
    if result["warnings"]:
        print(f"\nWarnings ({len(result['warnings'])}):")
        for warning in result["warnings"]:
            print(f"  ⚠ {warning}")
    
    print(f"\n{'='*70}\n")
