# """
# Enhanced PDF parser with intelligent table merging.

# Improvements:
# - Merges fragmented tables that belong together
# - Better handling of multi-section rate tables
# - Preserves all rows including header and subheader rows
# """

# from __future__ import annotations

# import logging
# import re
# from pathlib import Path
# from typing import Any

# import pdfplumber

# logger = logging.getLogger(__name__)


# def parse_pdf(file_path: Path) -> dict:
#     """
#     Parse PDF and extract text and tables to markdown format.
    
#     Enhanced to intelligently merge related tables that are fragmented.
    
#     Args:
#         file_path: Path to PDF file
        
#     Returns:
#         Dictionary with 'markdown', 'parsed_content', and 'markdown_path'
#     """
#     logger.info("Parsing PDF: %s", file_path)
    
#     parsed_content = []
    
#     with pdfplumber.open(file_path) as pdf:
#         page_count = len(pdf.pages)
#         logger.info("PDF has %d pages", page_count)
        
#         for page_num, page in enumerate(pdf.pages, 1):
#             logger.info("Processing page %d/%d", page_num, page_count)
            
#             # Extract all structured content from this page
#             page_segments = extract_page_content(page, page_num)
#             parsed_content.extend(page_segments)
    
#     # Try OCR if available and content is sparse
#     ocr_content = extract_ocr_if_needed(file_path, parsed_content)
#     if ocr_content:
#         parsed_content.extend(ocr_content)
    
#     # Generate final markdown
#     markdown_text = generate_markdown(parsed_content)
    
#     # Save to file
#     markdown_path = file_path.with_suffix(".md")
#     markdown_path.write_text(markdown_text, encoding="utf-8")
    
#     logger.info("Generated markdown saved to: %s", markdown_path)
    
#     return {
#         "markdown": markdown_text,
#         "parsed_content": parsed_content,
#         "markdown_path": str(markdown_path),
#     }


# def extract_page_content(page: Any, page_num: int) -> list[dict]:
#     """
#     Extract all content (text and tables) from a single page.
    
#     Strategy:
#     1. Extract tables using pdfplumber
#     2. Merge related/fragmented tables
#     3. Extract text outside table regions
#     4. Organize by vertical position
    
#     Args:
#         page: pdfplumber page object
#         page_num: Page number
        
#     Returns:
#         List of content segments with their positions
#     """
#     segments = []
    
#     # Step 1: Extract all tables
#     table_bboxes = []
#     raw_tables = []
    
#     try:
#         tables = page.find_tables(
#             table_settings={
#                 "vertical_strategy": "lines",
#                 "horizontal_strategy": "lines",
#             }
#         )
#         logger.debug("Found %d table regions on page %d", len(tables), page_num)
        
#         for table_idx, table in enumerate(tables):
#             bbox = table.bbox
#             table_bboxes.append(bbox)
#             rows = table.extract()
            
#             if rows:
#                 raw_tables.append({
#                     "bbox": bbox,
#                     "rows": rows,
#                     "index": table_idx
#                 })
#                 logger.debug("Table %d: %d rows x %d cols", table_idx, len(rows), len(rows[0]) if rows else 0)
    
#     except Exception as e:
#         logger.warning("Table detection failed on page %d: %s", page_num, e)
    
#     # Step 2: Merge related tables (fragmented rate tables, etc)
#     merged_tables = merge_related_tables(raw_tables)
    
#     # Step 3: Convert merged tables to markdown
#     for merged_table in merged_tables:
#         md_table = create_markdown_table(merged_table["rows"])
#         if md_table:
#             segments.append({
#                 "page": page_num,
#                 "type": "table",
#                 "top": merged_table["bbox"][1],
#                 "text": md_table,
#             })
#             logger.debug("Created merged table with %d rows", len(merged_table["rows"]))
    
#     # Step 4: Extract text outside table regions
#     text_segments = extract_text_outside_tables(page, page_num, table_bboxes)
#     segments.extend(text_segments)
    
#     # Sort by vertical position
#     segments.sort(key=lambda x: x["top"])
    
#     return segments


# def merge_related_tables(raw_tables: list[dict]) -> list[dict]:
#     """
#     Intelligently merge tables that are fragmented or related.
    
#     Detects patterns like:
#     - Header table followed by data rows tables
#     - Rate tables split by term lengths
#     - Vehicle category headers with rate rows
    
#     Args:
#         raw_tables: List of extracted raw tables with bboxes
        
#     Returns:
#         List of merged table structures
#     """
#     if not raw_tables:
#         return []
    
#     merged = []
#     skip_indices = set()
    
#     for i, table in enumerate(raw_tables):
#         if i in skip_indices:
#             continue
        
#         # Check if this is a header/structure table
#         rows = table["rows"]
#         current_rows = [list(row) for row in rows]  # Copy rows
        
#         # Look for following tables to merge
#         j = i + 1
#         while j < len(raw_tables):
#             next_table = raw_tables[j]
#             next_rows = next_table["rows"]
            
#             # Check if tables should be merged
#             if should_merge_tables(current_rows, next_rows):
#                 # Merge: add next_rows to current_rows
#                 # Skip empty rows and headers
#                 for row in next_rows:
#                     # Skip if row is all header-like or all empty
#                     if not is_header_row(row) and any(cell and cell.strip() for cell in row):
#                         current_rows.append(list(row))
                
#                 skip_indices.add(j)
#                 logger.debug(f"Merged table {i} with table {j}")
#                 j += 1
#             else:
#                 break
        
#         merged.append({
#             "bbox": table["bbox"],
#             "rows": current_rows,
#         })
    
#     return merged


# def should_merge_tables(prev_rows: list[list[str]], next_rows: list[list[str]]) -> bool:
#     """
#     Determine if two consecutive tables should be merged.
    
#     Heuristics:
#     - Same number of columns
#     - Previous table is header/structure
#     - Next table contains data (rates, numbers)
#     - Within close proximity vertically
    
#     Args:
#         prev_rows: Previous table rows
#         next_rows: Next table rows
        
#     Returns:
#         True if tables should be merged
#     """
#     if not prev_rows or not next_rows:
#         return False
    
#     prev_cols = len(prev_rows[0])
#     next_cols = len(next_rows[0])
    
#     # Must have same number of columns
#     if prev_cols != next_cols:
#         return False
    
#     # Check if next table has numeric data
#     next_has_numbers = any(
#         any(re.search(r'\d+', cell or '') for cell in row)
#         for row in next_rows
#     )
    
#     if not next_has_numbers:
#         return False
    
#     # Check if previous table looks like header (has percentages or tier info)
#     prev_has_structure = any(
#         any(
#             '%' in (cell or '') or 
#             'TIER' in (cell or '').upper() or
#             'FICO' in (cell or '').upper()
#             for cell in row
#         )
#         for row in prev_rows
#     )
    
#     return prev_has_structure


# def is_header_row(row: list[str]) -> bool:
#     """
#     Check if a row is a header/structural row (should skip when merging).
    
#     Args:
#         row: Row to check
        
#     Returns:
#         True if row appears to be header
#     """
#     if not row or all(not cell or not cell.strip() for cell in row):
#         return True
    
#     # Rows that are mostly category labels
#     row_text = ' '.join(str(cell or '') for cell in row).upper()
#     header_keywords = ['AUTO', 'VEHICLE', 'MOS', 'MONTHS', 'TERM', 'NEW', 'USED']
    
#     keyword_count = sum(1 for kw in header_keywords if kw in row_text)
#     return keyword_count >= 2


# def create_markdown_table(rows: list[list[str]]) -> str | None:
#     """
#     Convert table rows to markdown format.
    
#     Args:
#         rows: List of rows, each row is a list of cells
        
#     Returns:
#         Markdown table string or None if invalid
#     """
#     if not rows or not rows[0]:
#         return None
    
#     # Clean cells
#     cleaned_rows = []
#     for row in rows:
#         cleaned_row = [clean_cell(cell) for cell in row]
#         # Skip rows that are entirely empty
#         if any(cell.strip() for cell in cleaned_row):
#             cleaned_rows.append(cleaned_row)
    
#     if not cleaned_rows:
#         return None
    
#     # Pad all rows to same length
#     max_cols = max(len(row) for row in cleaned_rows)
#     padded_rows = [row + [""] * (max_cols - len(row)) for row in cleaned_rows]
    
#     # Remove columns that are entirely empty
#     col_has_content = [False] * max_cols
#     for row in padded_rows:
#         for i, cell in enumerate(row):
#             if cell.strip():
#                 col_has_content[i] = True
    
#     keep_cols = [i for i, has_content in enumerate(col_has_content) if has_content]
#     if not keep_cols:
#         return None
    
#     filtered_rows = [
#         [row[i] for i in keep_cols]
#         for row in padded_rows
#     ]
    
#     # Generate markdown
#     if not filtered_rows:
#         return None
    
#     lines = []
    
#     # Header row
#     header = filtered_rows[0]
#     lines.append("| " + " | ".join(header) + " |")
#     lines.append("| " + " | ".join("---" for _ in header) + " |")
    
#     # Data rows
#     for row in filtered_rows[1:]:
#         lines.append("| " + " | ".join(row) + " |")
    
#     return "\n".join(lines)


# def clean_cell(cell: Any) -> str:
#     """
#     Clean a table cell value.
    
#     Args:
#         cell: Cell value (can be None, str, etc)
        
#     Returns:
#         Cleaned cell string
#     """
#     if cell is None:
#         return ""
    
#     text = str(cell).strip()
    
#     # Remove common placeholder characters
#     if text in ("$", "S", "-", "–", "—"):
#         return ""
    
#     # Normalize whitespace
#     text = re.sub(r"\s+", " ", text)
    
#     return text


# def normalize_text(text: str) -> str:
#     """
#     Normalize text content.
    
#     Handles:
#     - Bullet point conversion (• → numbered list)
#     - Multiple spaces
#     - Trailing/leading whitespace
    
#     Args:
#         text: Raw text
        
#     Returns:
#         Normalized text
#     """
#     lines = text.split("\n")
#     out = []
#     bullet_num = 1
    
#     for line in lines:
#         stripped = line.strip()
        
#         if not stripped:
#             out.append("")
#             continue
        
#         # Convert bullets to numbered lists
#         if stripped and stripped[0] in ("•", "◦", "○", "■"):
#             out.append(f"{bullet_num}. {stripped[1:].strip()}")
#             bullet_num += 1
#         else:
#             out.append(stripped)
#             # Reset numbering on blank line
#             if not stripped:
#                 bullet_num = 1
    
#     # Join and normalize whitespace
#     result = "\n".join(out)
#     result = re.sub(r"\n\s*\n+", "\n\n", result)  # Multiple blank lines → single
#     result = result.strip()
    
#     return result


# def extract_text_outside_tables(
#     page: Any, page_num: int, table_bboxes: list[tuple]
# ) -> list[dict]:
#     """
#     Extract text content that is NOT within table regions.
    
#     Args:
#         page: pdfplumber page object
#         page_num: Page number
#         table_bboxes: List of table bounding boxes to exclude
        
#     Returns:
#         List of text segments
#     """
#     segments = []
    
#     # Extract raw text first
#     full_text = page.extract_text() or ""
#     if not full_text.strip():
#         logger.warning("No text extracted from page %d", page_num)
#         return segments
    
#     # Split into lines
#     lines = page.extract_text_lines(return_chars=False)
#     if not lines:
#         # Fallback: use extract_text and split manually
#         text_para = normalize_text(full_text)
#         if text_para.strip():
#             segments.append({
#                 "page": page_num,
#                 "type": "text",
#                 "top": 0,
#                 "text": text_para,
#             })
#         return segments
    
#     # Filter lines that are outside table regions
#     in_table_threshold = 30  # pixels of tolerance
#     text_block = []
#     block_top = None
#     block_gap_threshold = 18  # gap between paragraphs
    
#     for line in lines:
#         y_top = line["top"]
        
#         # Check if this line is inside any table bbox
#         in_table = any(
#             bbox[1] - in_table_threshold <= y_top <= bbox[3] + in_table_threshold
#             for bbox in table_bboxes
#         )
        
#         if in_table:
#             # Save accumulated text block before table
#             if text_block:
#                 block_text = "\n".join(l["text"] for l in text_block).strip()
#                 if block_text:
#                     normalized = normalize_text(block_text)
#                     if normalized:
#                         segments.append({
#                             "page": page_num,
#                             "type": "text",
#                             "top": block_top,
#                             "text": normalized,
#                         })
#                 text_block = []
#                 block_top = None
#             continue
        
#         # This line is outside tables
#         if not text_block:
#             text_block = [line]
#             block_top = y_top
#         else:
#             # Check if there's a large gap (paragraph break)
#             prev_line_bottom = text_block[-1]["bottom"]
#             gap = y_top - prev_line_bottom
            
#             if gap > block_gap_threshold:
#                 # Save this block and start new one
#                 block_text = "\n".join(l["text"] for l in text_block).strip()
#                 if block_text:
#                     normalized = normalize_text(block_text)
#                     if normalized:
#                         segments.append({
#                             "page": page_num,
#                             "type": "text",
#                             "top": block_top,
#                             "text": normalized,
#                         })
#                 text_block = [line]
#                 block_top = y_top
#             else:
#                 # Accumulate with previous line
#                 text_block.append(line)
    
#     # Don't forget the last block
#     if text_block:
#         block_text = "\n".join(l["text"] for l in text_block).strip()
#         if block_text:
#             normalized = normalize_text(block_text)
#             if normalized:
#                 segments.append({
#                     "page": page_num,
#                     "type": "text",
#                     "top": block_top,
#                     "text": normalized,
#                 })
    
#     return segments


# def extract_ocr_if_needed(
#     file_path: Path, parsed_content: list[dict]
# ) -> list[dict]:
#     """
#     Run OCR only if text extraction yielded very little content.
    
#     Args:
#         file_path: Path to PDF file
#         parsed_content: Already extracted content
        
#     Returns:
#         Additional OCR content segments (if any)
#     """
#     # Calculate content coverage
#     total_text_length = sum(
#         len(item.get("text", ""))
#         for item in parsed_content
#         if item.get("type") == "text"
#     )
    
#     # If we have reasonable content, skip OCR
#     if total_text_length > 500:
#         logger.debug("Skipping OCR - sufficient text content extracted (%d chars)", total_text_length)
#         return []
    
#     logger.info("Text content sparse (%d chars) - attempting OCR", total_text_length)
    
#     ocr_segments = []
#     try:
#         from pdf2image import convert_from_path
#         import pytesseract
        
#         with pdfplumber.open(file_path) as pdf:
#             for page_num in range(1, len(pdf.pages) + 1):
#                 try:
#                     images = convert_from_path(
#                         str(file_path),
#                         dpi=200,
#                         first_page=page_num,
#                         last_page=page_num,
#                     )
                    
#                     if not images:
#                         continue
                    
#                     # Convert to grayscale
#                     gray = images[0].convert("L")
                    
#                     # Run OCR
#                     ocr_text = pytesseract.image_to_string(gray, config="--psm 6").strip()
                    
#                     if ocr_text:
#                         normalized = normalize_text(ocr_text)
#                         if normalized and len(normalized) > 50:
#                             ocr_segments.append({
#                                 "page": page_num,
#                                 "type": "ocr",
#                                 "top": 99999,  # At end
#                                 "text": normalized,
#                             })
#                             logger.debug("OCR extracted %d chars from page %d", len(normalized), page_num)
                
#                 except Exception as e:
#                     logger.warning("OCR failed for page %d: %s", page_num, e)
    
#     except ImportError:
#         logger.info("pdf2image or pytesseract not available - skipping OCR")
#     except Exception as e:
#         logger.warning("OCR processing failed: %s", e)
    
#     return ocr_segments


# def generate_markdown(segments: list[dict]) -> str:
#     """
#     Generate final markdown document from segments.
    
#     Args:
#         segments: List of content segments
        
#     Returns:
#         Complete markdown text
#     """
#     # Group by page
#     pages: dict[int, list[dict]] = {}
#     for segment in segments:
#         page_num = segment.get("page", 1)
#         pages.setdefault(page_num, []).append(segment)
    
#     # Sort segments within each page
#     for page_segments in pages.values():
#         page_segments.sort(key=lambda x: x.get("top", 0))
    
#     # Build markdown
#     parts = []
#     for page_num in sorted(pages.keys()):
#         parts.append(f"## Page {page_num}")
        
#         for segment in pages[page_num]:
#             text = segment.get("text", "").strip()
#             if text:
#                 parts.append(text)
        
#         parts.append("")  # Blank line between pages
    
#     return "\n\n".join(parts).strip() + "\n"
