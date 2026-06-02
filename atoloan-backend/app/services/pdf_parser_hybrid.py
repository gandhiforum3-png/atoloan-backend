"""
Hybrid PDF Parser

Tries pdfplumber (v2) first — it produces cleaner markdown tables on
well-structured PDFs. Falls back to PyMuPDF when pdfplumber finds no
tables or scores significantly worse, which handles complex multi-column
layouts and multi-page rate sheets.

Drop-in replacement for pdf_parser_v2.parse_pdf:
  Returns {"markdown": str, "parsed_content": list, "markdown_path": str, "parser_used": str}
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# --- quality scoring (mirrors pdf_parser_comparison.py) ---

_RATE_RE = re.compile(r"\d+\.\d+%")
_TERM_RE = re.compile(r"\b(24|36|48|60|72|84|96|120)\s*(?:months?|mo\.?)\b", re.I)
_SCORE_RE = re.compile(r"\b[4-8]\d{2}\b")


def _score(parsed_content: list[dict], markdown: str) -> int:
    tables = sum(1 for s in parsed_content if s.get("type") == "table")
    rows = sum(s["text"].count("\n") for s in parsed_content if s.get("type") == "table")
    rates = len(_RATE_RE.findall(markdown))
    terms = len(_TERM_RE.findall(markdown))
    scores = len(_SCORE_RE.findall(markdown))
    return tables * 5 + rows * 2 + rates * 4 + terms * 3 + scores * 2


def _run_pdfplumber(file_path: Path) -> dict:
    from app.services.pdf_parser_v2 import parse_pdf
    return parse_pdf(file_path)


def _run_pymupdf(file_path: Path) -> dict:
    """PyMuPDF extraction — tables via fitz, text blocks outside table regions."""
    import fitz

    def _rows_to_md(rows: list) -> str:
        if not rows or len(rows) < 2:
            return ""

        def _c(v) -> str:
            return str(v).replace("|", "\\|").replace("\n", " ").strip() if v is not None else ""

        header = "| " + " | ".join(_c(c) for c in rows[0]) + " |"
        sep    = "| " + " | ".join("---" for _ in rows[0]) + " |"
        body   = "\n".join("| " + " | ".join(_c(c) for c in row) + " |" for row in rows[1:])
        return "\n".join([header, sep, body])

    md_parts: list[str] = []
    parsed_content: list[dict] = []

    doc = fitz.open(str(file_path))
    for page_num, page in enumerate(doc, 1):
        page_parts: list[tuple[float, str]] = []
        table_rects = []

        for tab in page.find_tables():
            try:
                df = tab.to_pandas()
                rows = [list(df.columns)] + df.values.tolist()
                md = _rows_to_md(rows)
                if md:
                    y = tab.bbox[1]
                    page_parts.append((y, md))
                    table_rects.append(fitz.Rect(tab.bbox))
                    parsed_content.append({"page": page_num, "type": "table", "top": y, "text": md})
            except Exception as e:
                logger.warning("PyMuPDF table error p%d: %s", page_num, e)

        for b in page.get_text("blocks", sort=True):
            if b[6] != 0:
                continue
            if any(fitz.Rect(b[:4]).intersects(tr) for tr in table_rects):
                continue
            text = b[4].strip()
            if text:
                y = b[1]
                page_parts.append((y, text))
                parsed_content.append({"page": page_num, "type": "text", "top": y, "text": text})

        page_parts.sort(key=lambda x: x[0])
        md_parts.extend(p for _, p in page_parts)
        md_parts.append("")

    doc.close()
    return {"markdown": "\n".join(md_parts), "parsed_content": parsed_content}


# ---------------------------------------------------------------------------
# PUBLIC API — same signature as pdf_parser_v2.parse_pdf
# ---------------------------------------------------------------------------

# How much better PyMuPDF must score to override a pdfplumber result that
# already found at least one table.
_OVERRIDE_THRESHOLD = 1.20   # PyMuPDF must score ≥ 20% higher to win


def parse_pdf(file_path: str | Path) -> dict:
    """
    Hybrid PDF parser.  Tries pdfplumber first; falls back to PyMuPDF when
    pdfplumber finds no tables or PyMuPDF scores ≥20% higher.

    Returns the same dict shape as pdf_parser_v2.parse_pdf:
      {
        "markdown":      str,
        "parsed_content": list[dict],
        "markdown_path": str,
        "parser_used":   str,   # extra diagnostic key
      }
    """
    file_path = Path(file_path)

    # --- pdfplumber pass ---
    plumber_result: dict | None = None
    plumber_score = 0
    try:
        plumber_result = _run_pdfplumber(file_path)
        plumber_score = _score(
            plumber_result.get("parsed_content", []),
            plumber_result.get("markdown", ""),
        )
        logger.info("pdfplumber score: %d", plumber_score)
    except Exception as e:
        logger.warning("pdfplumber failed: %s — trying PyMuPDF", e)

    # --- PyMuPDF pass (always run — both are fast CPU operations) ---
    mupdf_result: dict | None = None
    mupdf_score = 0
    try:
        mupdf_result = _run_pymupdf(file_path)
        mupdf_score = _score(
            mupdf_result.get("parsed_content", []),
            mupdf_result.get("markdown", ""),
        )
        logger.info("PyMuPDF score: %d", mupdf_score)
    except Exception as e:
        logger.warning("PyMuPDF failed: %s", e)

    # --- decision ---
    if plumber_result is None and mupdf_result is None:
        raise RuntimeError(f"Both parsers failed on {file_path.name}")

    if plumber_result is None:
        winner_result, winner_name = mupdf_result, "PyMuPDF"
    elif mupdf_result is None:
        winner_result, winner_name = plumber_result, "pdfplumber"
    elif mupdf_score >= plumber_score * _OVERRIDE_THRESHOLD:
        winner_result, winner_name = mupdf_result, "PyMuPDF"
        logger.info(
            "PyMuPDF wins (score %d vs pdfplumber %d) for %s",
            mupdf_score, plumber_score, file_path.name,
        )
    else:
        winner_result, winner_name = plumber_result, "pdfplumber"
        logger.info(
            "pdfplumber wins (score %d vs PyMuPDF %d) for %s",
            plumber_score, mupdf_score, file_path.name,
        )

    # --- save winning markdown ---
    markdown_path = file_path.with_suffix(".md")
    markdown_path.write_text(winner_result["markdown"], encoding="utf-8")

    logger.info("Hybrid parser used %s for %s", winner_name, file_path.name)

    return {
        "markdown": winner_result["markdown"],
        "parsed_content": winner_result.get("parsed_content", []),
        "markdown_path": str(markdown_path),
        "parser_used": winner_name,
    }
