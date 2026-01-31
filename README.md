# atoloan-backend

FastAPI test service with a Hello World endpoint and PostgreSQL connectivity.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Set `DATABASE_URL` in your environment (see `.env.example`).

## Run

```bash
uvicorn app.main:app --reload
```

## Endpoints

- `GET /hello` -> `{"message": "hello world"}`
- `GET /db-check` -> `{"status": "ok"}` if DB connection works
