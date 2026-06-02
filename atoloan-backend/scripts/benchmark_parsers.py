"""
Benchmark script: compare pdfplumber vs PyMuPDF vs Unstructured
on one or more rate sheet PDFs.

Usage (from atoloan-backend/atoloan-backend/):
    python scripts/benchmark_parsers.py
    python scripts/benchmark_parsers.py upload_pdf/KEYPOINT\ CU.pdf
    python scripts/benchmark_parsers.py --all        # run on every PDF in upload_pdf/
    python scripts/benchmark_parsers.py --save       # also save markdown files to /tmp/
"""

import argparse
import logging
import sys
from pathlib import Path

# Make sure app is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

from app.services.pdf_parser_comparison import compare_parsers

UPLOAD_DIR = Path(__file__).parent.parent / "upload_pdf"

# PDFs known to be good test cases (varied structure)
DEFAULT_SAMPLES = [
    "KEYPOINT CU.pdf",
    "SF FIRE CU.pdf",        # known hard case (multi-page tables)
    "COAST CENTRAL CU.pdf",
    "F3 CU.pdf",
]


def run_one(pdf_path: Path, save: bool = False) -> dict:
    print(f"\n>>> Parsing: {pdf_path.name}")
    report = compare_parsers(pdf_path)
    print(report["summary"])

    if save:
        out_dir = Path("/tmp/parser_benchmark") / pdf_path.stem
        out_dir.mkdir(parents=True, exist_ok=True)
        for raw in report["raw"]:
            fname = raw["parser"].split()[0].lower() + ".md"
            (out_dir / fname).write_text(raw["markdown"], encoding="utf-8")
        print(f"  Markdown files saved to: {out_dir}/")

    return report


def aggregate_summary(reports: list[dict]) -> None:
    from collections import defaultdict

    totals: dict[str, dict] = defaultdict(lambda: {
        "quality_score": 0, "rate_extractions": 0, "table_count": 0,
        "table_rows": 0, "term_extractions": 0, "wins": 0, "errors": 0,
    })

    for r in reports:
        for s in r["results"]:
            p = s["parser"]
            if s["error"]:
                totals[p]["errors"] += 1
                continue
            for key in ("quality_score", "rate_extractions", "table_count",
                        "table_rows", "term_extractions"):
                totals[p][key] += s[key]
        totals[r["winner"]]["wins"] += 1

    print("\n" + "=" * 70)
    print("  AGGREGATE RESULTS ACROSS ALL PDFs")
    print("=" * 70)
    print(f"{'Parser':<25} {'Wins':>5} {'QScore':>8} {'Tables':>7} "
          f"{'Rows':>6} {'Rates':>6} {'Errors':>7}")
    print("-" * 70)
    for parser, t in totals.items():
        print(
            f"{parser:<25} {t['wins']:>5} {t['quality_score']:>8} "
            f"{t['table_count']:>7} {t['table_rows']:>6} "
            f"{t['rate_extractions']:>6} {t['errors']:>7}"
        )
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Benchmark PDF parsers on rate sheets")
    parser.add_argument("pdfs", nargs="*", help="PDF file paths (optional)")
    parser.add_argument("--all", action="store_true", help="Run on all PDFs in upload_pdf/")
    parser.add_argument("--save", action="store_true", help="Save markdown output to /tmp/")
    args = parser.parse_args()

    if args.all:
        pdf_paths = sorted(UPLOAD_DIR.glob("*.pdf"))
    elif args.pdfs:
        pdf_paths = [Path(p) for p in args.pdfs]
    else:
        pdf_paths = [UPLOAD_DIR / name for name in DEFAULT_SAMPLES if (UPLOAD_DIR / name).exists()]

    if not pdf_paths:
        print("No PDFs found. Check upload_pdf/ directory or pass paths explicitly.")
        sys.exit(1)

    reports = []
    for path in pdf_paths:
        if not path.exists():
            print(f"  Skipping (not found): {path}")
            continue
        reports.append(run_one(path, save=args.save))

    if len(reports) > 1:
        aggregate_summary(reports)


if __name__ == "__main__":
    main()
