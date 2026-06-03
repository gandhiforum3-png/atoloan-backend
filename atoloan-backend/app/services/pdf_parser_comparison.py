"""
PDF Parser Comparison: pdfplumber (v2) vs PyMuPDF vs Unstructured

Runs all three parsers on a given PDF and produces a side-by-side
quality report covering:
  - Table detection (count, row/col completeness)
  - Text coverage (char count)
  - Rate/percentage extraction (critical for rate sheets)
  - Structural preservation (headers, tiers, terms)
  - Parse time
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PARSER 1 — existing pdfplumber-based parser (v2)
# ---------------------------------------------------------------------------

def parse_with_pdfplumber(file_path: Path) -> dict:
    """Wrapper around the existing pdf_parser_v2."""
    from app.services.pdf_parser_v2 import parse_pdf

    start = time.perf_counter()
    result = parse_pdf(file_path)
    elapsed = time.perf_counter() - start

    return {
        "parser": "pdfplumber (v2)",
        "markdown": result.get("markdown", ""),
        "parsed_content": result.get("parsed_content", []),
        "elapsed_sec": round(elapsed, 3),
        "error": None,
    }


# ---------------------------------------------------------------------------
# PARSER 2 — PyMuPDF (fitz)
# ---------------------------------------------------------------------------

def _pymupdf_rows_to_markdown(rows: list[list[str]]) -> str:
    """Convert a list of row-lists into a GitHub-flavoured markdown table."""
    if not rows or len(rows) < 2:
        return ""

    def _cell(c: Any) -> str:
        return str(c).replace("|", "\\|").replace("\n", " ").strip() if c else ""

    header = "| " + " | ".join(_cell(c) for c in rows[0]) + " |"
    sep = "| " + " | ".join("---" for _ in rows[0]) + " |"
    body = "\n".join(
        "| " + " | ".join(_cell(c) for c in row) + " |"
        for row in rows[1:]
    )
    return "\n".join([header, sep, body])


def parse_with_pymupdf(file_path: Path) -> dict:
    """
    Parse PDF with PyMuPDF (fitz).

    Strategy:
    1. Extract tables from each page using fitz's built-in table finder.
    2. For text outside tables, extract blocks and clean up whitespace.
    3. Sort all segments by vertical position and render to markdown.
    """
    import fitz  # pymupdf

    start = time.perf_counter()
    markdown_parts: list[str] = []
    parsed_content: list[dict] = []

    try:
        doc = fitz.open(str(file_path))

        for page_num, page in enumerate(doc, 1):
            page_md_parts: list[tuple[float, str]] = []  # (y_pos, text)

            # ---- tables ----
            tabs = page.find_tables()
            table_rects = []

            for tab in tabs:
                try:
                    df = tab.to_pandas()
                    rows = [list(df.columns)] + df.values.tolist()
                    md_table = _pymupdf_rows_to_markdown(rows)
                    if md_table:
                        y = tab.bbox[1]
                        page_md_parts.append((y, md_table))
                        table_rects.append(fitz.Rect(tab.bbox))
                        parsed_content.append({
                            "page": page_num,
                            "type": "table",
                            "top": y,
                            "text": md_table,
                        })
                except Exception as e:
                    logger.warning("PyMuPDF table extraction error page %d: %s", page_num, e)

            # ---- text blocks outside table regions ----
            blocks = page.get_text("blocks", sort=True)
            for b in blocks:
                # b = (x0, y0, x1, y1, text, block_no, block_type)
                if b[6] != 0:  # skip image blocks
                    continue
                rect = fitz.Rect(b[:4])
                if any(rect.intersects(tr) for tr in table_rects):
                    continue
                text = b[4].strip()
                if text:
                    y = b[1]
                    page_md_parts.append((y, text))
                    parsed_content.append({
                        "page": page_num,
                        "type": "text",
                        "top": y,
                        "text": text,
                    })

            # sort by y position and append
            page_md_parts.sort(key=lambda x: x[0])
            for _, part in page_md_parts:
                markdown_parts.append(part)

            markdown_parts.append("")  # blank line between pages

        doc.close()
        markdown = "\n".join(markdown_parts)

    except Exception as e:
        logger.error("PyMuPDF parse failed: %s", e)
        return {
            "parser": "PyMuPDF",
            "markdown": "",
            "parsed_content": [],
            "elapsed_sec": round(time.perf_counter() - start, 3),
            "error": str(e),
        }

    return {
        "parser": "PyMuPDF",
        "markdown": markdown,
        "parsed_content": parsed_content,
        "elapsed_sec": round(time.perf_counter() - start, 3),
        "error": None,
    }


# ---------------------------------------------------------------------------
# PARSER 3 — Unstructured
# ---------------------------------------------------------------------------

def parse_with_unstructured(file_path: Path) -> dict:
    """
    Parse PDF with the unstructured library.

    Strategy:
    1. Use partition_pdf() with hi_res=False (fast mode using pdfminer).
    2. Convert each element to markdown based on its category
       (Table → markdown table, Title/Header → heading, etc.)
    """
    from unstructured.partition.pdf import partition_pdf

    start = time.perf_counter()
    markdown_parts: list[str] = []
    parsed_content: list[dict] = []

    try:
        elements = partition_pdf(
            filename=str(file_path),
            strategy="fast",          # uses pdfminer — no vision model required
            infer_table_structure=True,
        )

        for elem in elements:
            category = elem.category
            text = str(elem).strip()
            if not text:
                continue

            # Approximate vertical position from metadata if available
            y = 0.0
            if hasattr(elem, "metadata") and elem.metadata:
                coords = getattr(elem.metadata, "coordinates", None)
                if coords and hasattr(coords, "points"):
                    try:
                        y = float(coords.points[0][1])
                    except Exception:
                        pass

            if category == "Table":
                # unstructured stores HTML table in metadata.text_as_html
                html = getattr(elem.metadata, "text_as_html", None)
                md_table = _html_table_to_markdown(html) if html else text
                markdown_parts.append(md_table)
                parsed_content.append({
                    "page": getattr(elem.metadata, "page_number", None),
                    "type": "table",
                    "top": y,
                    "text": md_table,
                })
            elif category in ("Title", "Header"):
                md = f"## {text}"
                markdown_parts.append(md)
                parsed_content.append({
                    "page": getattr(elem.metadata, "page_number", None),
                    "type": "header",
                    "top": y,
                    "text": md,
                })
            else:
                markdown_parts.append(text)
                parsed_content.append({
                    "page": getattr(elem.metadata, "page_number", None),
                    "type": "text",
                    "top": y,
                    "text": text,
                })

        markdown = "\n\n".join(markdown_parts)

    except Exception as e:
        logger.error("Unstructured parse failed: %s", e)
        return {
            "parser": "Unstructured",
            "markdown": "",
            "parsed_content": [],
            "elapsed_sec": round(time.perf_counter() - start, 3),
            "error": str(e),
        }

    return {
        "parser": "Unstructured",
        "markdown": markdown,
        "parsed_content": parsed_content,
        "elapsed_sec": round(time.perf_counter() - start, 3),
        "error": None,
    }


def _html_table_to_markdown(html: str) -> str:
    """Convert an HTML table string to a GitHub markdown table."""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        rows_html = soup.find_all("tr")
        rows: list[list[str]] = []
        for tr in rows_html:
            cells = [td.get_text(separator=" ").strip() for td in tr.find_all(["th", "td"])]
            if cells:
                rows.append(cells)

        if len(rows) < 2:
            return soup.get_text()

        # Normalise column count
        max_cols = max(len(r) for r in rows)
        rows = [r + [""] * (max_cols - len(r)) for r in rows]

        def _cell(c: str) -> str:
            return c.replace("|", "\\|").replace("\n", " ").strip()

        header = "| " + " | ".join(_cell(c) for c in rows[0]) + " |"
        sep = "| " + " | ".join("---" for _ in rows[0]) + " |"
        body = "\n".join(
            "| " + " | ".join(_cell(c) for c in row) + " |"
            for row in rows[1:]
        )
        return "\n".join([header, sep, body])

    except Exception:
        return html


# ---------------------------------------------------------------------------
# SCORING / METRICS
# ---------------------------------------------------------------------------

_RATE_PATTERN = re.compile(r"\d+\.\d+%")
_SCORE_PATTERN = re.compile(r"\b[4-8]\d{2}\b")  # FICO 400-899
_TERM_PATTERN = re.compile(r"\b(24|36|48|60|72|84|96|120)\s*(?:months?|mo\.?)\b", re.I)
_DOLLAR_PATTERN = re.compile(r"\$[\d,]+")


def _count_tables(parsed_content: list[dict]) -> int:
    return sum(1 for s in parsed_content if s.get("type") == "table")


def _table_rows(parsed_content: list[dict]) -> int:
    """Rough row count across all markdown tables."""
    total = 0
    for s in parsed_content:
        if s.get("type") == "table":
            total += s["text"].count("\n")
    return total


def score_result(result: dict) -> dict:
    """Compute quality metrics for a single parser result."""
    md = result.get("markdown", "") or ""
    pc = result.get("parsed_content", []) or []

    rates = _RATE_PATTERN.findall(md)
    scores = _SCORE_PATTERN.findall(md)
    terms = _TERM_PATTERN.findall(md)
    dollars = _DOLLAR_PATTERN.findall(md)
    table_count = _count_tables(pc)
    table_rows = _table_rows(pc)

    return {
        "parser": result["parser"],
        "error": result.get("error"),
        "elapsed_sec": result.get("elapsed_sec"),
        "char_count": len(md),
        "table_count": table_count,
        "table_rows": table_rows,
        "rate_extractions": len(rates),
        "credit_score_refs": len(scores),
        "term_extractions": len(terms),
        "dollar_amounts": len(dollars),
        # composite quality score (higher = better)
        "quality_score": (
            len(rates) * 4
            + len(terms) * 3
            + table_rows * 2
            + len(scores) * 2
            + len(dollars)
            + table_count * 5
        ),
    }


# ---------------------------------------------------------------------------
# MAIN COMPARISON FUNCTION
# ---------------------------------------------------------------------------

def compare_parsers(file_path: str | Path) -> dict:
    """
    Run all three parsers on a PDF and return a comparison report.

    Args:
        file_path: Path to the PDF file.

    Returns:
        dict with keys:
          - 'file': filename
          - 'results': list of per-parser score dicts
          - 'winner': name of best parser
          - 'summary': human-readable comparison text
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"PDF not found: {file_path}")

    logger.info("Comparing parsers on: %s", file_path.name)

    raw_results = []
    for parser_fn in (parse_with_pdfplumber, parse_with_pymupdf, parse_with_unstructured):
        try:
            raw_results.append(parser_fn(file_path))
        except Exception as e:
            logger.error("Parser %s crashed: %s", parser_fn.__name__, e)
            raw_results.append({
                "parser": parser_fn.__name__,
                "markdown": "",
                "parsed_content": [],
                "elapsed_sec": 0,
                "error": str(e),
            })

    scores = [score_result(r) for r in raw_results]

    # Determine winner (ignore errored parsers)
    valid = [s for s in scores if not s["error"]]
    winner = max(valid, key=lambda s: s["quality_score"])["parser"] if valid else "none"

    summary = _build_summary(scores, winner)

    return {
        "file": file_path.name,
        "results": scores,
        "winner": winner,
        "summary": summary,
        "raw": raw_results,  # full markdown available for further inspection
    }


def _build_summary(scores: list[dict], winner: str) -> str:
    lines = [
        "=" * 70,
        f"  PDF PARSER COMPARISON REPORT",
        "=" * 70,
        f"{'Parser':<25} {'Tables':>7} {'Rows':>6} {'Rates':>6} {'Terms':>6} "
        f"{'Scores':>7} {'$':>5} {'Chars':>7} {'Sec':>5} {'QScore':>7}",
        "-" * 70,
    ]
    for s in scores:
        if s["error"]:
            lines.append(f"{s['parser']:<25}  ERROR: {s['error'][:40]}")
        else:
            lines.append(
                f"{s['parser']:<25} "
                f"{s['table_count']:>7} "
                f"{s['table_rows']:>6} "
                f"{s['rate_extractions']:>6} "
                f"{s['term_extractions']:>6} "
                f"{s['credit_score_refs']:>7} "
                f"{s['dollar_amounts']:>5} "
                f"{s['char_count']:>7} "
                f"{s['elapsed_sec']:>5} "
                f"{s['quality_score']:>7}"
            )
    lines += [
        "-" * 70,
        f"  Winner: {winner}",
        "=" * 70,
    ]
    return "\n".join(lines)
