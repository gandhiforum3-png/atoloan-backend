# """
# PDF Parser - Improved version for robust content extraction.

# This parser has been updated to:
# 1. Use hierarchical extraction strategies
# 2. Properly handle table detection
# 3. Validate output against source PDF
# 4. Minimize data corruption and loss
# """

# from __future__ import annotations

# from pathlib import Path
# import logging

# import pdfplumber

# logger = logging.getLogger(__name__)


# def parse_pdf(file_path: Path, validate_output: bool = True) -> dict:
#     import re
#     from statistics import median

#     parsed_content = []
#     camelot_tables_by_page: dict[int, list[list[list[str]]]] = {}
#     logging.info("Parsing PDF: %s", file_path)

#     # --------------------------
#     # Helper functions
#     # --------------------------
#     def clean_cell(cell):
#         if cell is None:
#             return ""
#         txt = str(cell).replace("\n", " ").strip()
#         if txt in ("$", "S"):
#             return ""
#         return re.sub(r"\s+", " ", txt)


#     def group_words_to_lines(words, y_tol=4):
#         """Group nearby words into lines (by 'top' coordinate)."""
#         lines = {}
#         for w in words:
#             top = round(float(w.get("top", w.get("y0", 0))), 1)
#             key = next((k for k in lines if abs(k - top) <= y_tol), top)
#             lines.setdefault(key, []).append(w)
#         results = []
#         for k in sorted(lines):
#             ws = sorted(lines[k], key=lambda w: float(w["x0"]))
#             text = " ".join([w.get("text", "").strip() for w in ws]).strip()
#             bbox = (
#                 min(float(w["x0"]) for w in ws),
#                 min(float(w.get("top", w.get("y0", 0))) for w in ws),
#                 max(float(w["x1"]) for w in ws),
#                 max(float(w.get("bottom", w.get("y1", 0))) for w in ws),
#             )
#             results.append({"top": k, "text": text, "words": ws, "bbox": bbox})
#         return results


#     def infer_columns_from_words(words, gap_multiplier=1.4, min_gap=15.0):
#         """
#         Infer coarse column boundaries using centers but aggressively merge close x positions.
#         This prevents one visual column from splitting into multiple micro-columns.
#         """
#         if not words:
#             return [], []

#         # Use centers, rounded to nearest pixel
#         centers = sorted({round((float(w["x0"]) + float(w["x1"])) / 2.0, 1) for w in words})
#         if len(centers) == 1:
#             c = centers[0]
#             return [c], [(c - 50, c + 50)]

#         # Compute gaps and a robust gap threshold
#         gaps = [centers[i + 1] - centers[i] for i in range(len(centers) - 1)]
#         base_thr = median(gaps)
#         gap_thr = max(min_gap, base_thr * gap_multiplier)

#         # Cluster nearby x positions together into one column
#         clusters = []
#         current = [centers[0], centers[0]]
#         for x in centers[1:]:
#             if x - current[1] > gap_thr:
#                 clusters.append(tuple(current))
#                 current = [x, x]
#             else:
#                 current[1] = x
#         clusters.append(tuple(current))

#         mids, edges = [], []
#         for c in clusters:
#             mids.append((c[0] + c[1]) / 2.0)
#             edges.append((c[0] - 2.0, c[1] + 2.0))
#         return mids, edges


#     def looks_like_table(words):
#         """
#         Heuristic to detect a table region:
#         - Many numeric or '%' tokens
#         - Multiple distinct x positions
#         """
#         if not words or len(words) < 8:
#             return False
#         numeric_ratio = sum(bool(re.search(r"[\d%]", w["text"])) for w in words) / len(words)
#         xs = {round((float(w["x0"]) + float(w["x1"])) / 2.0, 1) for w in words}
#         return numeric_ratio > 0.3 and len(xs) >= 4  # likely a table


#     def reconstruct_table(page, bbox, all_words):
#         """
#         Robust table reconstruction:
#         ✅ merges wrapped rows into one (e.g., (MSRP/RKBB) + <73 months)
#         ✅ splits combined headers like '12 - 24 Months 25 - 36 Months'
#         ✅ merges intra-column words properly
#         """
#         x0, y0, x1, y1 = bbox
#         pad_x = max(5.0, (x1 - x0) * 0.02)
#         pad_y = max(2.0, (y1 - y0) * 0.02)

#         words = [
#             w for w in all_words
#             if (x0 - pad_x <= float(w["x0"]) <= x1 + pad_x)
#             and (y0 - pad_y <= float(w["top"]) <= y1 + pad_y)
#         ]
#         if len(words) < 6:
#             return None

#         # Require numeric or percentage presence to call it a table
#         numeric_ratio = sum(bool(re.search(r"[\d%]", w["text"])) for w in words) / len(words)
#         if numeric_ratio < 0.2:
#             return None

#         # group into visual lines
#         line_rows = group_words_to_lines(words, y_tol=4)
#         mids, edges = infer_columns_from_words(words)
#         ncols = len(mids)
#         if ncols < 2:
#             return None

#         reconstructed = []
#         last_row = None
#         for ln in line_rows:
#             cols = [[] for _ in range(ncols)]
#             for w in ln["words"]:
#                 center = (float(w["x0"]) + float(w["x1"])) / 2.0
#                 idx = min(range(ncols), key=lambda i: abs(mids[i] - center))
#                 cols[idx].append(w["text"])
#             merged = [" ".join(c).strip() for c in cols]

#             # ✅ If this line seems like continuation (very short and starts with '(' or '<'),
#             # merge it with previous row instead of new one
#             joined_text = " ".join(merged).strip()
#             if last_row and (joined_text.startswith("(") or joined_text.startswith("<")):
#                 last_row = [
#                     (f"{a} {b}".strip() if b else a)
#                     for a, b in zip(last_row + [""] * (len(merged) - len(last_row)), merged)
#                 ]
#                 reconstructed[-1] = last_row
#             else:
#                 reconstructed.append(merged)
#                 last_row = merged

#         # ✅ Fix merged "Months" columns (e.g. "12 - 24 Months 25 - 36 Months")
#         def split_month_header(text):
#             parts = re.findall(r"\d+\s*-\s*\d+\s*Months?", text)
#             if len(parts) > 1:
#                 return parts
#             return [text]

#         if reconstructed:
#             header = reconstructed[0]
#             new_header = []
#             for cell in header:
#                 new_header.extend(split_month_header(cell))
#             if len(new_header) > len(header):
#                 reconstructed[0] = new_header

#         # merge single-cell header rows (if very short)
#         final_rows = []
#         for row in reconstructed:
#             non_empty = [c for c in row if c]
#             if len(non_empty) <= 2 and len(" ".join(non_empty)) > 12:
#                 final_rows.append([" ".join(non_empty)])
#             else:
#                 final_rows.append(row)

#         return final_rows



#     def normalize_bullets(text):
#         lines = text.split("\n")
#         out, n = [], 1
#         for l in lines:
#             s = l.strip()
#             if s.startswith(("•", "", "o", "")):
#                 out.append(f"{n}. {s[1:].strip()}")
#                 n += 1
#             else:
#                 out.append(s)
#         return "\n".join(out)

#     def split_columns(text):
#         return [c.strip() for c in re.split(r"\s{2,}", text.strip()) if c.strip()]

#     def is_table_row(cols):
#         if len(cols) < 2:
#             return False
#         numeric_cells = sum(1 for c in cols if re.search(r"\d", c))
#         has_rate = any("%" in c for c in cols)
#         has_term = any("MOS" in c.upper() for c in cols)
#         has_loan = any("MAX LOAN" in c.upper() for c in cols)
#         return numeric_cells >= 2 or has_rate or has_term or has_loan



#     def markdown_table(rows):
#         rows = normalize_table_rows(rows)
#         if not rows:
#             return ""
#         header = rows[0]
#         header_is_data = sum(1 for c in header if re.search(r"\d", c)) >= 2
#         if header_is_data:
#             header = [f"Col {i+1}" for i in range(len(rows[0]))]
#             body = rows
#         else:
#             body = rows[1:]
#         lines = [
#             "| " + " | ".join(clean_cell(c) for c in header) + " |",
#             "| " + " | ".join("---" for _ in header) + " |",
#         ]
#         for row in body:
#             row = row + [""] * (len(header) - len(row))
#             lines.append("| " + " | ".join(clean_cell(c) for c in row) + " |")
#         return "\n".join(lines)

#     def normalize_table_rows(rows):
#         if not rows:
#             return []
#         cleaned = [[clean_cell(c) for c in row] for row in rows]
#         max_cols = max(len(r) for r in cleaned)
#         padded = [r + [""] * (max_cols - len(r)) for r in cleaned]
#         # drop columns that are empty across all rows
#         keep_indices = [
#             idx for idx in range(max_cols)
#             if any(row[idx].strip() for row in padded)
#         ]
#         if not keep_indices:
#             return []
#         normalized = [
#             [row[idx] for idx in keep_indices]
#             for row in padded
#         ]
#         # Fill blank cells from merged PDF cells (left-first, then up).
#         for i in range(len(normalized)):
#             for j in range(len(normalized[i])):
#                 if normalized[i][j]:
#                     continue
#                 if j > 0 and normalized[i][j - 1]:
#                     normalized[i][j] = normalized[i][j - 1]
#                 elif i > 0 and normalized[i - 1][j]:
#                     normalized[i][j] = normalized[i - 1][j]
#         return normalized

#     def extract_auto_loans_table(lines):
#         start_idx = None
#         end_idx = None
#         for i, ln in enumerate(lines):
#             text = ln["text"].strip()
#             upper = text.upper()
#             if "AUTO LOANS" in upper:
#                 start_idx = i
#                 continue
#             if start_idx is not None and (
#                 "PROGRAM GUIDELINES" in upper
#                 or "GUIDELINES AND QUALIFICATIONS" in upper
#                 or "CONTACTS AND LIENHOLDER" in upper
#             ):
#                 end_idx = i
#                 break
#         if start_idx is None:
#             return None
#         block = lines[start_idx + 1 : end_idx]
#         header_scores = []
#         for ln in block[:3]:
#             header_scores = re.findall(r"\b\d{3}\+|\b\d{3}-\d{3}\b|<\s*\d{3}", ln["text"])
#             if header_scores:
#                 break

#         rows = []
#         for ln in block:
#             text = ln["text"].strip()
#             if not text:
#                 continue
#             if any(k in text.upper() for k in ["MAX LTV", "RATE ADJUSTMENTS", "ABSOLUTE FLOOR"]):
#                 continue
#             term_matches = list(re.finditer(r"\b(36|48|60|72|84|96)\b", text))
#             if not term_matches:
#                 continue
#             label = text[: term_matches[0].start()].strip()
#             for idx, tm in enumerate(term_matches):
#                 start = tm.start()
#                 end = term_matches[idx + 1].start() if idx + 1 < len(term_matches) else len(text)
#                 segment = text[start:end]
#                 term = tm.group(1)
#                 rates = re.findall(r"\d+(?:\.\d+)?%", segment)
#                 if rates:
#                     rows.append([label if idx == 0 else "", term] + rates)

#         if not rows:
#             return None

#         max_rates = max(len(r) - 2 for r in rows)
#         scores = header_scores[:max_rates]
#         if len(scores) < max_rates:
#             scores.extend([f"Rate {i+1}" for i in range(len(scores), max_rates)])
#         header = ["Vehicle Age", "Term"] + scores
#         table_rows = [header] + rows
#         md = markdown_table(table_rows)
#         top = lines[start_idx]["top"] if start_idx is not None else 0
#         return {
#             "top": top,
#             "text": md,
#             "start_idx": start_idx,
#             "end_idx": end_idx,
#         }

#     def normalize_text(text):
#         return re.sub(r"\s+", " ", text.strip()).lower()

#     def has_similar_segment(segments, needle):
#         needle_norm = normalize_text(needle)
#         for seg in segments:
#             if needle_norm in normalize_text(seg["text"]):
#                 return True
#         return False
#     def columns_from_wordline(word_line, mids):
#         if not word_line["words"]:
#             return []
#         if not mids:
#             return split_columns(word_line["text"])
#         cols = [[] for _ in range(len(mids))]
#         for w in word_line["words"]:
#             center = (float(w["x0"]) + float(w["x1"])) / 2.0
#             idx = min(range(len(mids)), key=lambda i: abs(mids[i] - center))
#             cols[idx].append(w.get("text", ""))
#         return [" ".join(c).strip() for c in cols]


#     def table_blocks_from_word_lines(word_lines, mids):
#         blocks = []
#         current = []
#         for ln in word_lines:
#             cols = columns_from_wordline(ln, mids)
#             if is_table_row(cols):
#                 current.append((ln, cols))
#             else:
#                 if current:
#                     blocks.append(current)
#                     current = []
#         if current:
#             blocks.append(current)

#         results = []
#         for block in blocks:
#             rows = [cols for _, cols in block]
#             numeric_rows = sum(1 for r in rows if sum(1 for c in r if re.search(r"\d", c)) >= 2)
#             max_cols = max((len(r) for r in rows), default=0)
#             if numeric_rows == 0:
#                 continue
#             if len(rows) < 3 and max_cols < 5:
#                 continue
#             md = markdown_table(rows)
#             if md:
#                 top = min(item[0]["bbox"][1] for item in block)
#                 bottom = max(item[0]["bbox"][3] for item in block)
#                 results.append({"top": top, "bottom": bottom, "text": md})
#         return results


#     def to_markdown_table(rows):
#         if not rows:
#             return ""
#         header = rows[0]
#         lines = [
#             "| " + " | ".join(clean_cell(c) for c in header) + " |",
#             "| " + " | ".join("---" for _ in header) + " |",
#         ]
#         for row in rows[1:]:
#             lines.append("| " + " | ".join(clean_cell(c) for c in row) + " |")
#         return "\n".join(lines)


#     # --------------------------
#     # Optional Camelot table extraction (better column detection)
#     # --------------------------
#     try:
#         import camelot

#         camelot_tables = camelot.read_pdf(str(file_path), pages="all", flavor="lattice")
#         if camelot_tables.n == 0:
#             camelot_tables = camelot.read_pdf(str(file_path), pages="all", flavor="stream")
#         for t in camelot_tables:
#             try:
#                 page_num = int(t.page)
#             except (TypeError, ValueError):
#                 continue
#             rows = t.df.fillna("").values.tolist()
#             if rows:
#                 camelot_tables_by_page.setdefault(page_num, []).append(rows)
#         logging.info("Camelot tables found: %s", camelot_tables.n)
#     except Exception as exc:
#         logging.info("Camelot unavailable or failed: %s", exc)

#     # --------------------------
#     # Main PDF parsing
#     # --------------------------
#     # pdf_path = pdf_path  # change as needed

#     best_auto_table_text = None
#     page_count = 0
#     with pdfplumber.open(file_path) as pdf:
#         page_count = len(pdf.pages)
#         for page_num, page in enumerate(pdf.pages, 1):
#             logging.info("Parsing page %s", page_num)
#             all_words = page.extract_words(x_tolerance=1, y_tolerance=1)
#             page_width = page.width
#             logging.info("Extracted %s words", len(all_words))
#             try:
#                 tables = page.find_tables(
#                     table_settings={"vertical_strategy": "lines", "horizontal_strategy": "lines"}
#                 )
#             except Exception:
#                 tables = page.find_tables()
#             logging.info("Detected %s table regions", len(tables))
            
#             # FIX: also try splitting wide pages horizontally to catch distant term sets
#             bboxes = [t.bbox for t in tables]
#             fallback_bboxes = False
#             if not bboxes:
#                 width_half = page_width / 2
#                 bboxes = [
#                     (0, 0, width_half, page.height),
#                     (width_half, 0, page.width, page.height),
#                 ]
#                 fallback_bboxes = True
#                 logging.info("No table bboxes; using page split strategy")

#             segments = []
#             camelot_tables = camelot_tables_by_page.get(page_num, [])
#             for bbox in bboxes:
#                 if camelot_tables:
#                     break
#                 tab = reconstruct_table(page, bbox, all_words)
#                 if not tab:
#                     continue
#                 logging.info("Reconstructed table with %s rows", len(tab))
#                 header_idx = 0
#                 for i, r in enumerate(tab[:4]):
#                     if sum(bool(c) for c in r) > sum(bool(c) for c in tab[header_idx]):
#                         header_idx = i
#                 header, data = tab[: header_idx + 1], tab[header_idx + 1 :]
#                 table_rows = header + data
#                 table_md = to_markdown_table(table_rows)
#                 if table_md:
#                     segments.append({"top": bbox[1], "text": table_md})

#             # normal text outside tables
#             BLOCK_GAP = 18
#             lines = page.extract_text_lines(return_chars=False)
#             block, block_top = [], None
#             if not lines:
#                 fallback_text = page.extract_text() or ""
#                 if fallback_text.strip():
#                     parsed_content.append(
#                         {"page": page_num, "top": 0, "text": normalize_bullets(fallback_text)}
#                     )
#                     logging.info("Used fallback text extraction")
#                 parsed_content.extend({"page": page_num, "top": s["top"], "text": s["text"]} for s in segments)
#                 continue
#             logging.info("Extracted %s text lines", len(lines))
#             table_ranges = []
#             auto_table = None
#             word_lines = group_words_to_lines(all_words, y_tol=4)
#             mids, _edges = infer_columns_from_words(all_words)
#             if not segments:
#                 if not camelot_tables:
#                     text_table_blocks = table_blocks_from_word_lines(word_lines, mids)
#                     for block_item in text_table_blocks:
#                         segments.append({"top": block_item["top"], "text": block_item["text"]})
#                         table_ranges.append((block_item["top"], block_item["bottom"]))
#             auto_table = extract_auto_loans_table(lines)
#             if auto_table and not has_similar_segment(segments, "Auto Loans"):
#                 segments.append({"top": 99990, "text": auto_table["text"]})
#                 best_auto_table_text = auto_table["text"]
#             for i, ln in enumerate(lines):
#                 if auto_table and auto_table["start_idx"] is not None:
#                     end_idx = auto_table["end_idx"] or len(lines)
#                     if auto_table["start_idx"] <= i < end_idx:
#                         continue
#                 top, bottom = ln["top"], ln["bottom"]
#                 if any(y0 <= top <= y1 for (y0, y1) in table_ranges):
#                     continue
#                 inside = False if fallback_bboxes else any(
#                     y0 <= top <= y1 for (_, y0, _, y1) in bboxes
#                 )
#                 if inside:
#                     if block:
#                         txt = "\n".join(l["text"] for l in block).strip()
#                         if txt:
#                             parsed_content.append({"page": page_num, "top": block_top, "text": normalize_bullets(txt)})
#                         block = []
#                     continue
#                 if not block:
#                     block, block_top = [ln], top
#                 else:
#                     prev_bottom = lines[i - 1]["bottom"] if i else None
#                     if prev_bottom and top - prev_bottom > BLOCK_GAP:
#                         txt = "\n".join(l["text"] for l in block).strip()
#                         if txt:
#                             parsed_content.append({"page": page_num, "top": block_top, "text": normalize_bullets(txt)})
#                         block, block_top = [ln], top
#                     else:
#                         block.append(ln)
#             if block:
#                 txt = "\n".join(l["text"] for l in block).strip()
#                 if txt:
#                     parsed_content.append({"page": page_num, "top": block_top, "text": normalize_bullets(txt)})

#             parsed_content.extend({"page": page_num, "top": s["top"], "text": s["text"]} for s in segments)
#             if not segments and not any(item["page"] == page_num for item in parsed_content):
#                 fallback_text = page.extract_text() or ""
#                 if fallback_text.strip():
#                     parsed_content.append(
#                         {"page": page_num, "top": 0, "text": normalize_bullets(fallback_text)}
#                     )
#                     logging.info("Added fallback page text at end of page parsing")

#             # Camelot tables (if any) appended at end of page
#             for idx, table_rows in enumerate(camelot_tables, start=1):
#                 md = markdown_table(table_rows)
#                 if md and not has_similar_segment(segments, md):
#                     parsed_content.append(
#                         {"page": page_num, "top": 99990 + idx, "text": md}
#                     )

#     # --------------------------
#     # OCR pass (always run; merge with parsed content)
#     # --------------------------
#     ocr_pages: dict[int, str] = {}
#     try:
#         from pdf2image import convert_from_path
#         import pytesseract

#         for page_num in range(1, page_count + 1):
#             images = convert_from_path(
#                 str(file_path),
#                 dpi=300,
#                 first_page=page_num,
#                 last_page=page_num,
#             )
#             if not images:
#                 continue
#             gray = images[0].convert("L")
#             ocr_text = pytesseract.image_to_string(gray, config="--psm 6").strip()
#             if ocr_text:
#                 ocr_pages[page_num] = normalize_bullets(ocr_text)
#         logging.info("OCR completed for %s pages", len(ocr_pages))
#     except Exception as exc:
#         logging.info("OCR unavailable or failed: %s", exc)

#     # --------------------------
#     # Final output (structured tables + text + OCR)
#     # --------------------------
#     parsed_content.sort(key=lambda x: (x["page"], x["top"]))
#     page_items: dict[int, list[str]] = {}
#     for item in parsed_content:
#         page_items.setdefault(item["page"], []).append(item["text"])

#     def line_signature(text: str) -> str:
#         text = normalize_text(text)
#         text = re.sub(r"[^\w%$./-]+", " ", text)
#         return re.sub(r"\s+", " ", text).strip()

#     parts = []
#     all_pages = sorted(set(list(page_items.keys()) + list(ocr_pages.keys())))
#     for page_num in all_pages:
#         parts.append(f"## Page {page_num}")
#         if page_num in page_items:
#             parts.extend(page_items[page_num])
#         if page_num in ocr_pages:
#             structured_lines = []
#             for block in page_items.get(page_num, []):
#                 structured_lines.extend([ln for ln in block.splitlines() if ln.strip()])
#             structured_sigs = {line_signature(ln) for ln in structured_lines if line_signature(ln)}

#             ocr_lines = [ln for ln in ocr_pages[page_num].splitlines() if ln.strip()]
#             deduped = [ln for ln in ocr_lines if line_signature(ln) not in structured_sigs]
#             if deduped:
#                 parts.append("OCR TEXT")
#                 parts.append("\n".join(deduped))
#         parts.append("")

#     text = "\n\n".join(parts).strip()
#     markdown_path = file_path.with_suffix(".md")
#     markdown_path.write_text(text, encoding="utf-8")
#     return {"markdown": text, "parsed_content": parsed_content, "markdown_path": str(markdown_path)}
