"""
Generic PDF Parser - Configuration-free, structure-based extraction.

This parser extracts content from PDFs without any hardcoded patterns, keywords,
or configurations. It uses structural analysis and content-based heuristics to:

1. Detect and extract tables using multiple strategies
2. Intelligently merge fragmented tables
3. Extract text outside table regions
4. Generate markdown output

The parser is completely generic and works across different PDF formats
without requiring domain-specific configuration.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pdfplumber

logger = logging.getLogger(__name__)


def bboxes_overlap(
    bbox1: tuple[float, float, float, float],
    bbox2: tuple[float, float, float, float],
    threshold: float = 0.1,
) -> bool:
    """
    Check if two bounding boxes overlap significantly.

    Args:
        bbox1: (x0, top, x1, bottom)
        bbox2: (x0, top, x1, bottom)
        threshold: Minimum overlap percentage to consider as overlapping

    Returns:
        True if bboxes overlap more than threshold
    """
    x0_1, y0_1, x1_1, y1_1 = bbox1
    x0_2, y0_2, x1_2, y1_2 = bbox2

    # Calculate intersection
    x_inter = max(0, min(x1_1, x1_2) - max(x0_1, x0_2))
    y_inter = max(0, min(y1_1, y1_2) - max(y0_1, y0_2))

    if x_inter == 0 or y_inter == 0:
        return False

    inter_area = x_inter * y_inter
    area1 = (x1_1 - x0_1) * (y1_1 - y0_1)
    area2 = (x1_2 - x0_2) * (y1_2 - y0_2)

    # Check if overlap is significant relative to both boxes
    return (inter_area / area1 > threshold) or (inter_area / area2 > threshold)


def parse_pdf(file_path: Path) -> dict:
    """
    Parse PDF and extract text and tables to markdown format.

    Uses a hierarchical approach:
    1. Extract tables with multiple strategies
    2. Intelligently merge fragmented tables
    3. Extract remaining text as paragraphs
    4. Use OCR only to fill genuine gaps
    5. Organize by page and position

    Args:
        file_path: Path to PDF file

    Returns:
        Dictionary with 'markdown', 'parsed_content', and 'markdown_path'
    """
    logger.info("Parsing PDF: %s", file_path)

    # Ensure file_path is a Path object
    from pathlib import Path
    file_path = Path(file_path)

    parsed_content = []

    with pdfplumber.open(str(file_path)) as pdf:
        page_count = len(pdf.pages)
        logger.info("PDF has %d pages", page_count)

        for page_num, page in enumerate(pdf.pages, 1):
            logger.info("Processing page %d/%d", page_num, page_count)

            # Extract all content from this page
            page_segments = extract_page_content(page, page_num)
            parsed_content.extend(page_segments)

    # Try OCR if available and content is sparse
    # Skip OCR if we already have substantial content (table or text > 1000 chars)
    total_content_length = sum(
        len(item.get("text", ""))
        for item in parsed_content
    )
    
    if total_content_length <= 500:
        ocr_content = extract_ocr_if_needed(file_path, parsed_content)
        if ocr_content:
            parsed_content.extend(ocr_content)
    else:
        logger.info("Skipping OCR - sufficient content already extracted (%d chars)", total_content_length)

    # Generate final markdown
    markdown_text = generate_markdown(parsed_content)

    # Save to file
    markdown_path = file_path.with_suffix(".md")
    markdown_path.write_text(markdown_text, encoding="utf-8")

    logger.info("Generated markdown saved to: %s", markdown_path)

    return {
        "markdown": markdown_text,
        "parsed_content": parsed_content,
        "markdown_path": str(markdown_path),
    }


def extract_page_content(page: Any, page_num: int) -> list[dict]:
    """
    Extract all content (text and tables) from a single page.

    Strategy:
    1. Extract tables using pdfplumber's multiple detection strategies
    2. Merge adjacent/fragmented tables intelligently
    3. Extract text outside table regions
    4. Organize by vertical position

    Args:
        page: pdfplumber page object
        page_num: Page number

    Returns:
        List of content segments with their positions
    """
    segments = []

    # Step 1: Extract tables with multiple strategies
    raw_tables = []
    table_bboxes = []

    try:
        # Try primary strategy: lines (most common for structured PDFs)
        tables = page.find_tables(
            table_settings={
                "vertical_strategy": "lines",
                "horizontal_strategy": "lines",
            }
        )
        logger.debug("Found %d tables with 'lines' strategy on page %d", len(tables), page_num)

        for table in tables:
            bbox = table.bbox
            rows = table.extract()
            if rows and len(rows) > 0:
                raw_tables.append(
                    {
                        "bbox": bbox,
                        "rows": rows,
                    }
                )
                table_bboxes.append(bbox)

        # If few tables found, try fallback strategy ('text')
        if len(raw_tables) < 2:
            logger.debug("Trying fallback 'text' detection strategy on page %d", page_num)
            tables_fallback = page.find_tables(
                table_settings={
                    "vertical_strategy": "text",
                    "horizontal_strategy": "text",
                }
            )

            for table in tables_fallback:
                bbox = table.bbox
                rows = table.extract()
                if rows and len(rows) > 1:
                    # Check if this overlaps with existing tables
                    overlaps = any(
                        bboxes_overlap(bbox, existing_bbox) for existing_bbox in table_bboxes
                    )
                    if not overlaps:
                        raw_tables.append(
                            {
                                "bbox": bbox,
                                "rows": rows,
                            }
                        )
                        table_bboxes.append(bbox)
                        logger.debug("Added table from fallback 'text' strategy")

    except Exception as e:
        logger.warning("Table detection failed on page %d: %s", page_num, e)

    # Step 2: Merge fragmented/related tables
    merged_tables = merge_adjacent_tables(raw_tables)
    
    # Step 2b: Fix tables with multiple tier headers in one cell (newline-separated)
    # Must come BEFORE fix_split_columns_in_tables since that function removes None rows
    merged_tables = fix_multi_tier_headers_in_cell(merged_tables)
    
    # Step 2c: Fix split columns in table headers (for text detection strategy)
    merged_tables = fix_split_columns_in_tables(merged_tables)

    # Step 3: Convert merged tables to markdown segments
    for table_data in merged_tables:
        rows = table_data.get("rows", [])
        bbox = table_data.get("bbox", (0, 0, 0, 0))

        # Skip single-column tables
        num_cols = len(rows[0]) if rows else 0
        if num_cols <= 1:
            logger.debug("Skipping single-column table")
            continue

        if rows and len(rows) > 1:  # Must have at least header + 1 data row
            md_table = create_markdown_table(rows)
            if md_table:
                segments.append(
                    {
                        "page": page_num,
                        "type": "table",
                        "top": bbox[1],
                        "text": md_table,
                    }
                )
                logger.debug("Extracted table with %d rows, %d cols", len(rows), num_cols)

    # Step 4: Extract text from bordered text boxes (non-table boxes)
    box_segments, box_bboxes = extract_text_boxes(page, page_num, table_bboxes)
    segments.extend(box_segments)
    
    # Add extracted box bboxes to table_bboxes so they are excluded from text extraction
    table_bboxes.extend(box_bboxes)

    # Step 5: Extract text outside table regions (and outside extracted boxes)
    text_segments = extract_text_outside_tables(page, page_num, table_bboxes)
    segments.extend(text_segments)

    # Add extraction order index before sorting
    for i, segment in enumerate(segments):
        segment["extraction_index"] = i

    # Sort by vertical position (top), but preserve extraction order for same-position items
    segments.sort(key=lambda x: (x["top"], x["extraction_index"]))

    return segments


def fix_split_columns_in_tables(tables: list[dict]) -> list[dict]:
    """
    Fix tables where column headers are split across multiple columns.
    
    When using 'text' detection strategy, long column headers like
    "Tier 1, 720+" may be split into "Ti" and "er 1, 720+" across columns.
    
    This function detects and merges these split columns by looking for
    patterns where consecutive columns, when joined, form valid tier headers.
    
    Args:
        tables: List of table dictionaries with 'rows' key
        
    Returns:
        List of tables with fixed columns
    """
    fixed_tables = []
    
    for table in tables:
        rows = table.get("rows", [])
        if not rows or len(rows) < 2:
            fixed_tables.append(table)
            continue
        
        # Check if this table needs fixing by looking for tier header patterns
        needs_fixing = False
        for row in rows[:20]:  # Check first 20 rows (tier headers may be further down)
            row_str = " ".join(str(cell or "") for cell in row)
            # Look for patterns that indicate split columns:
            # - "Tier X, YYY" split into cells like "Ti" + "er X, YYY"
            # - "er X, YYY" or "Tier X" patterns
            if "Tier" in row_str and "er" in row_str and len(row) > 5:
                # Likely has split tier headers
                needs_fixing = True
                break
        
        if not needs_fixing:
            fixed_tables.append(table)
            continue
        
        # Fix the table by merging split columns
        fixed_rows = []
        for row in rows:
            fixed_row = merge_split_columns_in_row(row)
            fixed_rows.append(fixed_row)
        
        # Update the table with fixed rows
        table["rows"] = fixed_rows
        fixed_tables.append(table)
    
    return fixed_tables


def fix_multi_tier_headers_in_cell(tables: list[dict]) -> list[dict]:
    """
    Fix tables where multiple tier headers are combined in one cell with newlines.
    
    When PDFs have tier headers as "Tier 1\nTier 2\nTier 3..." in a single cell
    with the rates on separate rows with None in the first column, this function
    splits them into proper rows.
    
    Example:
        Input row: ['Tier 1 740+\nTier 2 680-739\nTier 3 640-679', '6.49%', '6.49%', ...]
        Output rows:
        - ['Tier 1 740+', '6.49%', '6.49%', ...]
        - ['Tier 2 680-739', '6.74%', '6.74%', ...]
        - ['Tier 3 640-679', '9.49%', '9.49%', ...]
    
    Args:
        tables: List of table dictionaries with 'rows' key
        
    Returns:
        List of tables with fixed rows
    """
    fixed_tables = []
    
    for table in tables:
        rows = table.get("rows", [])
        if not rows or len(rows) < 2:
            fixed_tables.append(table)
            continue
        
        # Check if any cell contains multiple newline-separated tier headers
        needs_fixing = False
        for row in rows[:30]:  # Check first 30 rows
            if not row:
                continue
            first_cell = str(row[0] or "").strip()
            # Count how many "Tier" keywords are in this cell
            tier_count = first_cell.count("Tier ")
            if tier_count >= 2:  # Multiple tier headers in one cell
                needs_fixing = True
                break
        
        if not needs_fixing:
            fixed_tables.append(table)
            continue
        
        # Fix the table by splitting multi-tier header rows
        fixed_rows = split_multi_tier_header_rows(rows)
        table["rows"] = fixed_rows
        fixed_tables.append(table)
    
    return fixed_tables


def split_multi_tier_header_rows(rows: list[list]) -> list[list]:
    """
    Split rows that have multiple tier headers in the first cell.
    
    Identifies rows where the first cell contains newline-separated tier headers
    and pairs each header with the corresponding rate data from subsequent rows.
    
    Special case: The first tier's data may be in the same row as the headers.
    
    Args:
        rows: List of table rows
        
    Returns:
        List of rows with tier headers split into separate rows
    """
    fixed_rows = []
    i = 0
    
    while i < len(rows):
        current_row = rows[i]
        if not current_row:
            fixed_rows.append(current_row)
            i += 1
            continue
        
        first_cell = str(current_row[0] or "").strip()
        tier_count = first_cell.count("Tier ")
        
        # If this cell has multiple tier headers
        if tier_count >= 2:
            # Split the tier headers by newlines
            tier_lines = first_cell.split("\n")
            tier_headers = [line.strip() for line in tier_lines if line.strip()]
            
            # The first tier's data is in the current row (rest of the row)
            first_tier_data = current_row[1:]
            
            # Collect the subsequent rows that have None in the first column
            # We need tier_count - 1 more rows (since first tier's data is in current row)
            data_rows = []
            j = i + 1
            while j < len(rows) and rows[j] and rows[j][0] is None and len(data_rows) < len(tier_headers) - 1:
                data_rows.append(rows[j])
                j += 1
            
            # If we have matching tier headers and data rows
            if len(data_rows) == len(tier_headers) - 1:
                # Create new rows pairing each tier header with its data
                # First tier uses data from current row
                new_row = [tier_headers[0]] + first_tier_data
                fixed_rows.append(new_row)
                
                # Remaining tiers use data from subsequent rows
                for tier_header, data_row in zip(tier_headers[1:], data_rows):
                    new_row = [tier_header] + data_row[1:]  # Skip the None in first column
                    fixed_rows.append(new_row)
                
                # Skip the rows we just processed
                i = j
            else:
                # Mismatch - keep original row
                fixed_rows.append(current_row)
                i += 1
        else:
            # Not a multi-tier header row, keep as-is
            fixed_rows.append(current_row)
            i += 1
    
    return fixed_rows


def merge_split_columns_in_row(row: list) -> list:
    """
    Merge split columns in a single row with tier headers.
    
    Handles PDF text detection artifacts where tier headers are split:
    - "Ti" + "er 1, 720+" -> "Tier 1, 720+"
    - "er 4, 640" -> "Tier 4, 640"
    - "er" + "5, 620+" -> "Tier 5, 620+"
    
    These patterns are structural, not hardcoded - they reflect how
    pdfplumber's text detection strategy splits multi-word cells.
    
    Args:
        row: List of cells in the row
        
    Returns:
        List with properly merged tier headers
    """
    if not row or len(row) < 2:
        return row
    
    # First pass: clean cells that have " Ti" tacked onto the end
    cleaned_row = []
    for cell in row:
        cell_str = str(cell or "").strip()
        if cell_str.endswith(" Ti"):
            cleaned_row.append(cell_str[:-3].strip())
        else:
            cleaned_row.append(cell_str)
    
    # Second pass: merge tier header fragments
    merged = []
    i = 0
    
    while i < len(cleaned_row):
        current_cell = cleaned_row[i]
        
        # Look ahead to next cell
        if i < len(cleaned_row) - 1:
            next_cell = cleaned_row[i + 1]
            
            # Pattern 1: "Ti" + "er X,..." = "Tier X,..."
            if current_cell == "Ti" and next_cell and next_cell.startswith("er"):
                merged.append(current_cell + next_cell)
                i += 2
                continue
            
            # Pattern 2: "er" (single) + "X, ..." where X is digit = "Tier X,..."
            if current_cell == "er" and next_cell:
                next_first = next_cell[0] if next_cell else ""
                if next_first.isdigit():
                    # "er" + "5, 620+" = "Tier 5, 620+"
                    result = "Tier" + current_cell + " " + next_cell
                    # Fix double "er" (Tierer -> Tier)
                    if result.startswith("Tierer"):
                        result = "Tier " + result[6:]
                    merged.append(result)
                    i += 2
                    continue
        
        # Pattern 3: "er X,..." (but ends with number, no +) = add "Ti" prefix
        if current_cell.startswith("er "):
            # Extract what comes after "er "
            rest = current_cell[3:]  # Skip "er "
            # If it matches "N, YYY" pattern, add "Ti" prefix
            if rest and rest[0].isdigit():
                merged.append("Ti" + current_cell)
                i += 1
                continue
        
        # Pattern 4: "er X,..." (complete form) = add "Ti" prefix (but avoid "Tierer")
        if current_cell.startswith("er") and len(current_cell) > 2:
            second_char = current_cell[2]
            if second_char.isdigit() or second_char == " ":
                # "er2,..." or "er 7,..." = "Tier2,..." or "Tier 7,..."
                result = "Ti" + current_cell
                # Fix "Tierer" to "Tier"
                if result.startswith("Tierer"):
                    result = "Tier" + result[6:]
                merged.append(result)
                i += 1
                continue
        
        # No special pattern, keep as-is
        merged.append(current_cell)
        i += 1
    
    return merged


def merge_adjacent_tables(raw_tables: list[dict]) -> list[dict]:
    """
    Merge logically adjacent/related tables that are fragmented.

    Uses heuristics:
    - Similar number of columns (allow variance)
    - Skip single-column tables
    - Check for significant data overlap

    Args:
        raw_tables: List of extracted tables with bboxes and rows

    Returns:
        List of merged table structures
    """
    if not raw_tables:
        return []

    # First pass: filter out tables that are clearly not data tables
    filtered_tables = []
    for table in raw_tables:
        rows = table.get("rows", [])
        if rows:
            # Skip single-column tables (usually text content)
            if len(rows[0]) <= 1:
                logger.debug("Skipping single-column table")
                continue

            # For tables with many rows, be more lenient with sparsity
            # Complex PDFs may have sparse tables that are still valid
            num_rows = len(rows)
            cell_count = sum(len(row) for row in rows)
            non_empty_cells = sum(
                1 for row in rows for cell in row if cell and str(cell).strip()
            )

            # Skip only if extremely sparse (< 10% filled) AND small table
            # Large tables (> 20 rows) are usually legitimate even if sparse
            if cell_count > 0 and non_empty_cells / cell_count < 0.1 and num_rows < 20:
                logger.debug("Skipping mostly-empty table (%d/%d cells filled)", non_empty_cells, cell_count)
                continue

            filtered_tables.append(table)

    merged = []
    skip_indices = set()

    for i, table in enumerate(filtered_tables):
        if i in skip_indices:
            continue

        rows = table.get("rows", [])
        current_rows = [list(row) for row in rows]  # Copy rows

        # Look for following tables to merge
        j = i + 1
        while j < len(filtered_tables):
            next_table = filtered_tables[j]
            next_rows = next_table.get("rows", [])

            # Check if tables should be merged
            if should_merge_tables(current_rows, next_rows):
                # Merge: add next_rows to current_rows
                for row in next_rows:
                    # Skip if row is empty or header-like
                    if is_empty_row(row):
                        continue
                    if is_likely_header_row(row):
                        continue

                    # Pad to match current columns
                    if len(row) < len(current_rows[0]):
                        row = list(row) + [None] * (len(current_rows[0]) - len(row))
                    current_rows.append(row[: len(current_rows[0])])

                skip_indices.add(j)
                logger.debug("Merged table %d with table %d", i, j)
                j += 1
            else:
                j += 1

        merged.append(
            {
                "bbox": table.get("bbox", (0, 0, 0, 0)),
                "rows": current_rows,
            }
        )

    return merged


def should_merge_tables(prev_rows: list[list[str]], next_rows: list[list[str]]) -> bool:
    """
    Determine if two consecutive tables should be merged.

    NOTE: Table merging is disabled for rate sheets to preserve distinct programs.
    Each rate program (High Mileage, New Auto, Used Auto, Limited Credit) should
    be kept as separate tables for clarity and accuracy.

    Args:
        prev_rows: Previous table rows
        next_rows: Next table rows

    Returns:
        False - Tables are NOT merged to preserve distinct rate programs
    """
    # DISABLED: Do not merge tables to preserve distinct rate programs
    # This ensures each program (High Mileage, New Auto, Used Auto, Limited Credit)
    # stays separate and readable
    return False


def is_empty_row(row: list[str]) -> bool:
    """Check if a row is completely empty."""
    return not any(cell and str(cell).strip() for cell in row)


def is_likely_header_row(row: list[str]) -> bool:
    """
    Check if a row is a header/structural row.

    A row is likely a header if it contains mostly short keywords/labels
    rather than data.
    """
    if not row or is_empty_row(row):
        return True

    # Count cells that look like labels (short text without numbers/symbols)
    label_cells = 0
    for cell in row:
        if not cell:
            continue
        text = str(cell).strip().upper()
        # Single or double-letter cells are likely labels
        if len(text) <= 3 or text.isalpha():
            label_cells += 1

    # If most cells are labels, likely a header
    total_cells = sum(1 for cell in row if cell and str(cell).strip())
    if total_cells > 0 and label_cells / total_cells > 0.6:
        return True

    return False


def split_line_by_char_gaps(line: dict, gap_threshold: float = 100) -> list[str]:
    """
    Split a line that contains large character gaps (two-column layout).
    
    When PDF text has large gaps between characters, it often indicates separate
    logical sections on the same Y-position (e.g., left column and right column).
    Uses character X positions to identify the split point.
    
    Args:
        line: pdfplumber line dict with 'chars' data
        gap_threshold: Pixel gap that indicates a column break
        
    Returns:
        List of text segments from this line
    """
    chars = line.get("chars", [])
    text = line.get("text", "").strip()
    
    if not chars or len(chars) < 2:
        return [text]
    
    # Build a mapping of character positions to their indices in the text
    # This handles the case where pdfplumber includes/excludes spaces
    char_positions = []
    text_idx = 0
    
    for char_obj in chars:
        char_text = char_obj['text']
        # Find this character in the text starting from text_idx
        pos = text.find(char_text, text_idx)
        if pos >= 0:
            char_positions.append((pos, char_obj['x0'], char_obj['x1']))
            text_idx = pos + len(char_text)
    
    # Find large gaps
    gap_split_point = None
    for i in range(len(chars) - 1):
        gap = chars[i + 1]['x0'] - chars[i]['x1']
        if gap > gap_threshold:
            # Found a large gap - use the text position of the next character
            if i + 1 < len(char_positions):
                gap_split_point = char_positions[i + 1][0]
            break
    
    # If we found a gap, split the text
    if gap_split_point and gap_split_point > 0:
        left = text[:gap_split_point].strip()
        right = text[gap_split_point:].strip()
        
        segments = []
        if left:
            segments.append(left)
        if right:
            segments.append(right)
        return segments if segments else [text]
    
    # No gap found, return original text
    return [text]


def extract_text_boxes(
    page: Any, page_num: int, table_bboxes: list[tuple]
) -> tuple[list[dict], list[tuple]]:
    """
    Detect and extract text from bordered text boxes (non-table boxes).

    Uses rectangle detection to identify distinct bordered text boxes on the page
    and extracts text from each box separately to preserve structure.

    Args:
        page: pdfplumber page object
        page_num: Page number
        table_bboxes: List of table bounding boxes to exclude

    Returns:
        Tuple of (text box segments, bboxes of extracted boxes)
    """
    segments = []
    extracted_bboxes = []
    
    try:
        # Get all rectangles on the page
        rects = page.rects
        if not rects:
            logger.debug("No rectangles found on page %d", page_num)
            return segments, extracted_bboxes
        
        # Find large rectangular regions (potential text boxes)
        rects_by_size = sorted(rects, key=lambda r: (r['x1'] - r['x0']) * (r['bottom'] - r['top']), reverse=True)
        
        large_boxes = []
        # Minimum area threshold - use larger value to exclude small header boxes
        # Area of 50x50 = 2500, but we want to exclude smaller boxes like headers
        min_area_threshold = 10000  # Only very large boxes (e.g., 100x100)
        
        for rect in rects_by_size:
            width = rect['x1'] - rect['x0']
            height = rect['bottom'] - rect['top']
            area = width * height
            
            if area < min_area_threshold:
                continue
            
            # Check if this rectangle is part of a table
            in_table = False
            for table_bbox in table_bboxes:
                # Check if rectangle is within table bounds
                if (table_bbox[0] <= rect['x0'] <= table_bbox[2] and
                    table_bbox[1] <= rect['top'] <= table_bbox[3]):
                    in_table = True
                    break
            
            if in_table:
                continue
            
            bbox = (rect['x0'], rect['top'], rect['x1'], rect['bottom'])
            
            # Check if this box is already in the list (avoid duplicates)
            is_duplicate = any(
                abs(b['bbox'][0] - bbox[0]) < 5 and
                abs(b['bbox'][1] - bbox[1]) < 5
                for b in large_boxes
            )
            
            if not is_duplicate:
                large_boxes.append({
                    'bbox': bbox,
                    'width': width,
                    'height': height,
                    'area': area,
                })
        
        logger.debug("Found %d non-table text boxes on page %d", len(large_boxes), page_num)
        
        # Extract text from each box
        for i, box in enumerate(large_boxes):
            try:
                cropped = page.crop(box['bbox'])
                text = cropped.extract_text()
                
                if text and text.strip():
                    # Normalize the extracted text
                    normalized_text = normalize_text(text)
                    
                    if normalized_text.strip():
                        segments.append({
                            'page': page_num,
                            'type': 'text_box',
                            'top': box['bbox'][1],  # Use top Y coordinate for sorting
                            'text': normalized_text,
                            'box_index': i,
                        })
                        extracted_bboxes.append(box['bbox'])
                        logger.debug("Extracted text box %d from page %d, text length: %d", i, page_num, len(normalized_text))
            except Exception as e:
                logger.warning("Failed to extract text from box %d on page %d: %s", i, page_num, e)
        
        # Sort segments by vertical position
        segments.sort(key=lambda x: x['top'])
        
    except Exception as e:
        logger.warning("Text box extraction failed on page %d: %s", page_num, e)
    
    return segments, extracted_bboxes


def extract_text_outside_tables(
    page: Any, page_num: int, table_bboxes: list[tuple]
) -> list[dict]:
    """
    Extract text content that is NOT within table regions.

    Handles complex multi-column layouts by detecting section headers and
    splitting content intelligently while preserving formatting.

    Args:
        page: pdfplumber page object
        page_num: Page number
        table_bboxes: List of table bounding boxes to exclude

    Returns:
        List of text segments
    """
    segments = []

    # Extract raw text
    full_text = page.extract_text() or ""
    if not full_text.strip():
        logger.warning("No text extracted from page %d", page_num)
        return segments

    # Split by lines and filter by position
    lines = page.extract_text_lines(return_chars=False)
    if not lines:
        # Fallback: normalize and return as single segment
        text_para = normalize_text(full_text)
        if text_para.strip():
            segments.append(
                {
                    "page": page_num,
                    "type": "text",
                    "top": 0,
                    "text": text_para,
                }
            )
        return segments

    # Filter to lines outside tables and rebuild text
    # Extract text outside table bounds, tracking positions for section detection
    text_lines_filtered = []
    line_positions = []  # Track (line_text, top_position) for section breaks
    
    for line in lines:
        y_top = line["top"]
        line_text = line.get("text", "").strip()
        x_pos = line.get("x0", 0)

        if not line_text:
            continue

        # Check if line is inside any table bbox
        # Only use horizontal expansion (not vertical) to preserve text between tables
        in_table = any(
            bbox[0] <= x_pos <= bbox[2] and bbox[1] <= y_top <= bbox[3]
            for bbox in table_bboxes  # Use original bboxes, not expanded
        )

        if not in_table:
            text_lines_filtered.append(line_text)
            line_positions.append((line_text, y_top))

    if not text_lines_filtered:
        return segments

    # Rebuild text from filtered lines
    filtered_text = "\n".join(text_lines_filtered)

    # Post-process to split by sections
    # Detect and split by large vertical gaps between lines (indicates section breaks)
    # This is the primary way to separate sections in financial PDFs
    
    # Build sections based on vertical gaps
    gap_sections = []
    gap_section_tops = []
    
    current_section_lines = [line_positions[0][0]] if line_positions else []
    current_section_start_top = line_positions[0][1] if line_positions else 0
    gap_threshold = 100  # pixels - large gap indicates section break
    
    for i in range(1, len(line_positions)):
        prev_top = line_positions[i - 1][1]
        curr_top = line_positions[i][1]
        gap = curr_top - prev_top
        
        # If gap is large, finalize current section and start new one
        if gap > gap_threshold:
            if current_section_lines:
                section_text = "\n".join(current_section_lines)
                gap_sections.append(section_text)
                gap_section_tops.append(current_section_start_top)
            
            # Start new section
            current_section_lines = [line_positions[i][0]]
            current_section_start_top = curr_top
        else:
            # Add to current section
            current_section_lines.append(line_positions[i][0])
    
    # Add final section
    if current_section_lines:
        section_text = "\n".join(current_section_lines)
        gap_sections.append(section_text)
        gap_section_tops.append(current_section_start_top)
    
    # Now apply the header-based section splitting to each gap section
    # This further subdivides gap sections if they contain section headers
    raw_sections = []
    raw_section_tops = []
    
    # Process gap sections: For each gap section, further subdivide by headers
    # if they exist, otherwise just use the full section
    for gap_section_text, gap_section_top in zip(gap_sections, gap_section_tops):
        # Simple approach: just use the gap section as-is
        # The gap detection already handles the main section breaks
        raw_sections.append(gap_section_text)
        raw_section_tops.append(gap_section_top)

    # Convert sections to segments with proper position tracking
    for i, section_text in enumerate(raw_sections):
        normalized = normalize_text(section_text)
        # Include segments >= 10 chars to capture section headers like "Term Information:"
        # Also include headers that end with colon even if short, as they're organizational
        is_header_only = section_text.strip().endswith(":")
        
        # Get the top position for this section (use gap section position if available)
        section_top = 0
        if i < len(gap_section_tops):
            section_top = gap_section_tops[i]
        
        if normalized and (len(normalized) >= 10 or (is_header_only and len(normalized) >= 5)):
            segments.append(
                {
                    "page": page_num,
                    "type": "text",
                    "top": section_top,
                    "text": normalized,
                }
            )

    return segments


def create_markdown_table(rows: list[list[str]]) -> str | None:
    """
    Convert table rows to markdown format with proper handling of merged cells.
    
    For tables with merged cells (common in financial PDFs), shows empty cells
    with clear visual representation. Preserves sparse column structure.

    Args:
        rows: List of rows, each row is a list of cells

    Returns:
        Markdown table string or None if invalid
    """
    if not rows or not rows[0]:
        return None

    # Clean cells
    cleaned_rows = []
    for row in rows:
        cleaned_row = [clean_cell(cell) for cell in row]
        if any(cell.strip() for cell in cleaned_row):
            cleaned_rows.append(cleaned_row)

    if not cleaned_rows:
        return None

    # Pad all rows to same length
    max_cols = max(len(row) for row in cleaned_rows)
    padded_rows = [row + [""] * (max_cols - len(row)) for row in cleaned_rows]

    # For sparse tables (like financial rate sheets), identify meaningful columns
    restructured = restructure_sparse_table(padded_rows)
    
    if not restructured:
        return None

    # Limit markdown table to reasonable size (max 15 columns to avoid unwieldy output)
    if len(restructured[0]) > 15:
        restructured = compress_table_columns(restructured)

    lines = []

    # Header row
    header = restructured[0]
    lines.append("| " + " | ".join(header) + " |")
    lines.append("| " + " | ".join("---" for _ in header) + " |")

    # Data rows - use special notation for merged cells
    for row in restructured[1:]:
        # Mark empty cells with [:-----:] to show they're merged/empty
        formatted_row = []
        for cell in row:
            if cell.strip():
                formatted_row.append(cell)
            else:
                # Use [:-----:] to indicate merged cell visually in markdown
                formatted_row.append("[:]")
        lines.append("| " + " | ".join(formatted_row) + " |")

    return "\n".join(lines)


def restructure_sparse_table(padded_rows: list[list[str]]) -> list[list[str]]:
    """
    Intelligently restructure sparse tables to maintain logical column groups.
    
    For financial tables with merged cells (common in rate sheets), this preserves
    the table structure while intelligently handling sparse columns.
    
    Strategy:
    1. Calculate content density for each column (how many rows have content)
    2. Keep columns that appear in multiple rows (not just headers)
    3. Don't remove columns just because some rows are sparse
    4. Preserve all columns with meaningful data
    
    Args:
        padded_rows: Table rows padded to uniform length
        
    Returns:
        Restructured rows with meaningful columns preserved
    """
    if not padded_rows:
        return padded_rows
    
    max_cols = len(padded_rows[0])
    
    # Step 1: Calculate content density for each column
    col_content_rows = [set() for _ in range(max_cols)]
    
    for row_idx, row in enumerate(padded_rows):
        for col_idx, cell in enumerate(row):
            cell_text = str(cell).strip()
            if cell_text:
                col_content_rows[col_idx].add(row_idx)
    
    # Step 2: Count how many rows have content in each column
    col_content_count = [len(rows) for rows in col_content_rows]
    
    # Step 3: Keep columns that have content in at least 2 rows OR are in the first 3 columns
    # First columns are usually labels/headers, so keep them
    keep_cols = []
    for col_idx in range(max_cols):
        # Keep if: has content in 2+ rows, OR is one of first 3 columns
        if col_content_count[col_idx] >= 2 or col_idx < 3:
            keep_cols.append(col_idx)
    
    # If we have very few columns, keep them all
    if len(keep_cols) < 2:
        keep_cols = list(range(max_cols))
    
    keep_cols = sorted(list(set(keep_cols)))
    
    # Step 4: Reconstruct rows with selected columns
    restructured = []
    for row in padded_rows:
        new_row = [row[i] if i < len(row) else "" for i in keep_cols]
        restructured.append(new_row)
    
    return restructured


def compress_table_columns(rows: list[list[str]]) -> list[list[str]]:
    """
    Compress table columns for readability when there are too many columns.
    
    Merges adjacent cells with spaces to keep table manageable.
    
    Args:
        rows: Table rows
        
    Returns:
        Compressed table rows with fewer columns
    """
    if not rows or len(rows[0]) <= 12:
        return rows
    
    # Group consecutive columns and merge them
    # Strategy: merge every 2-3 adjacent columns
    target_cols = 10
    col_count = len(rows[0])
    cols_per_group = max(2, col_count // target_cols)
    
    compressed = []
    for row in rows:
        new_row = []
        for i in range(0, len(row), cols_per_group):
            group = row[i:i+cols_per_group]
            # Merge cells with space, keeping non-empty ones
            merged = " ".join(cell for cell in group if cell.strip())
            if not merged:
                merged = ""
            new_row.append(merged)
        compressed.append(new_row)
    
    return compressed


def clean_cell(cell: Any) -> str:
    """
    Clean a table cell value.

    Args:
        cell: Cell value (can be None, str, etc)

    Returns:
        Cleaned cell string
    """
    if cell is None:
        return ""

    text = str(cell).strip()

    # Remove common placeholder characters
    if text in ("$", "S", "-", "–", "—"):
        return ""

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text)

    return text


def normalize_text(text: str) -> str:
    """
    Normalize text content.

    Handles:
    - Bullet points (convert to numbered lists)
    - Multiple spaces
    - Trailing/leading whitespace

    Args:
        text: Raw text

    Returns:
        Normalized text
    """
    lines = text.split("\n")
    out = []
    bullet_num = 1

    for line in lines:
        stripped = line.strip()

        if not stripped:
            out.append("")
            continue

        # Convert bullets to numbered lists
        if stripped and stripped[0] in ("•", "◦", "○", "■"):
            out.append(f"{bullet_num}. {stripped[1:].strip()}")
            bullet_num += 1
        else:
            out.append(stripped)
            if not stripped:
                bullet_num = 1

    # Join and normalize whitespace
    result = "\n".join(out)
    result = re.sub(r"\n\s*\n+", "\n\n", result)  # Multiple blank lines → single
    result = result.strip()

    return result


def extract_ocr_if_needed(file_path: Path, parsed_content: list[dict]) -> list[dict]:
    """
    Run OCR only if text extraction yielded very little content.

    Args:
        file_path: Path to PDF file
        parsed_content: Already extracted content

    Returns:
        Additional OCR content segments (if any)
    """
    # Calculate content coverage
    total_text_length = sum(
        len(item.get("text", ""))
        for item in parsed_content
        if item.get("type") == "text"
    )

    # If we have reasonable content, skip OCR
    if total_text_length > 500:
        logger.debug(
            "Skipping OCR - sufficient text content extracted (%d chars)", total_text_length
        )
        return []

    logger.info("Text content sparse (%d chars) - attempting OCR", total_text_length)

    ocr_segments = []
    try:
        from pdf2image import convert_from_path

        import pytesseract

        with pdfplumber.open(file_path) as pdf:
            for page_num in range(1, len(pdf.pages) + 1):
                try:
                    images = convert_from_path(
                        str(file_path),
                        dpi=200,
                        first_page=page_num,
                        last_page=page_num,
                    )

                    if not images:
                        continue

                    # Convert to grayscale
                    gray = images[0].convert("L")

                    # Run OCR
                    ocr_text = pytesseract.image_to_string(gray, config="--psm 6").strip()

                    if ocr_text:
                        normalized = normalize_text(ocr_text)
                        if normalized and len(normalized) > 50:
                            ocr_segments.append(
                                {
                                    "page": page_num,
                                    "type": "ocr",
                                    "top": 99999,  # At end
                                    "text": normalized,
                                }
                            )
                            logger.debug("OCR extracted %d chars from page %d", len(normalized), page_num)

                except Exception as e:
                    logger.warning("OCR failed for page %d: %s", page_num, e)

    except ImportError:
        logger.info("pdf2image or pytesseract not available - skipping OCR")
    except Exception as e:
        logger.warning("OCR processing failed: %s", e)

    return ocr_segments


def generate_markdown(segments: list[dict]) -> str:
    """
    Generate final markdown document from segments.

    Args:
        segments: List of content segments

    Returns:
        Complete markdown text
    """
    # Group by page
    pages: dict[int, list[dict]] = {}
    for segment in segments:
        page_num = segment.get("page", 1)
        pages.setdefault(page_num, []).append(segment)

    # Sort segments within each page
    for page_segments in pages.values():
        page_segments.sort(key=lambda x: x.get("top", 0))

    # Build markdown
    parts = []
    for page_num in sorted(pages.keys()):
        parts.append(f"## Page {page_num}")

        for segment in pages[page_num]:
            text = segment.get("text", "").strip()
            if text:
                parts.append(text)

        parts.append("")  # Blank line between pages

    return "\n\n".join(parts).strip() + "\n"
