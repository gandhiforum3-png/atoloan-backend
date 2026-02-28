"""
Shared fixtures for integration tests.
Loads the .env file so OPENAI_API_KEY, DB credentials, etc. are available.
"""
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the inner app root (atoloan-backend/atoloan-backend/.env)
_ENV_FILE = Path(__file__).parents[2] / ".env"
if _ENV_FILE.exists():
    load_dotenv(_ENV_FILE, override=False)
