#!/usr/bin/env python3
"""
Quick test to see if the parser is working and how long it takes
"""

import sys
import os
from pathlib import Path
import time

# Add the atoloan-backend directory to path
sys.path.insert(0, str(Path(__file__).parent / "atoloan-backend"))

# Load environment variables
from dotenv import load_dotenv
env_file = Path(__file__).parent / "atoloan-backend" / ".env.example"
if env_file.exists():
    print(f"✓ Loading environment from: {env_file}")
    load_dotenv(env_file)

# Check API key
api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    print("✗ OPENAI_API_KEY not set")
    sys.exit(1)
else:
    masked_key = api_key[:20] + "..." + api_key[-4:] if len(api_key) > 24 else "***"
    print(f"✓ OPENAI_API_KEY configured: {masked_key}")

# Import parser
try:
    from app.services.rate_sheet_parser import parse_rate_sheet_from_markdown
    print("✓ Successfully imported parser")
except Exception as e:
    print(f"✗ Failed to import: {e}")
    sys.exit(1)

# Read test markdown
markdown_file = Path(__file__).parent / "atoloan-backend" / "upload_pdf" / "AMERICAN FIRST CU.md"
if not markdown_file.exists():
    print(f"✗ Test file not found: {markdown_file}")
    sys.exit(1)

markdown_text = markdown_file.read_text()
print(f"✓ Read markdown file: {len(markdown_text)} chars")

# Test parser
print("\n" + "="*80)
print("Testing parser...")
print("="*80)

try:
    print(f"[{time.strftime('%H:%M:%S')}] Starting parse_rate_sheet_from_markdown...")
    sys.stdout.flush()
    
    start_time = time.time()
    result = parse_rate_sheet_from_markdown(markdown_text)
    elapsed = time.time() - start_time
    
    print(f"[{time.strftime('%H:%M:%S')}] Parser completed in {elapsed:.2f} seconds")
    sys.stdout.flush()
    
    if result:
        print(f"✓ Parser returned result: {type(result)}")
        print(f"✓ Credit Union: {result.credit_union_info.name if result.credit_union_info else 'N/A'}")
    else:
        print("✗ Parser returned None")
        
except Exception as e:
    print(f"✗ Parser failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n" + "="*80)
print("✓ Test complete")
print("="*80)
