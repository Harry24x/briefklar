# BriefKlar

> Explains German official letters and bureaucracy rules to international students in simple English, with an official source for every answer.

**Status:** work in progress (MVP in development). Live demo, results table and architecture diagram follow.

General information from official sources, not legal advice.

## Run locally (Windows PowerShell)

```powershell
# 1. Settings
Copy-Item .env.example .env      # then set POSTGRES_PASSWORD and the same password in DATABASE_URL

# 2. Database (PostgreSQL 16 + pgvector)
docker compose --env-file .env -f infra/docker-compose.yml up -d db

# 3. Backend
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m app.db                 # creates tables if they don't exist
uvicorn app.main:app --reload    # http://localhost:8000/health
```

## Tests and lint

```powershell
cd backend
ruff check . ; ruff format --check . ; pytest --cov=app
```

## Ingestion

```powershell
cd backend
python -m app.ingest.crawl --list    # show which official pages would be crawled
pip install -e ".[ml]"               # embedding model (PyTorch, large)
python -m app.ingest.crawl           # crawl, chunk, embed, store (safe to re-run)
```

## Tech stack

Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2 · PostgreSQL 16 + pgvector · LangGraph · Groq (Llama 3.3 70B) · multilingual-e5-small · bge-reranker-v2-m3 · Next.js + TypeScript + Tailwind · Docker · GitHub Actions
