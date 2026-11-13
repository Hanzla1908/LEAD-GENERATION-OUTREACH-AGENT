# AI-Powered Restaurant Lead Generation & Outreach System

A full-stack system for discovering restaurant leads and automating outreach using AI.

## Stack

- **Frontend**: React 18 + Vite + JavaScript
- **Backend**: Python + FastAPI
- **Database**: SQLite
- **AI**: Claude API (Anthropic)

## Project Structure

```
.
├── frontend/                  # React + Vite dashboard
│   ├── src/
│   │   ├── components/        # Reusable UI components
│   │   ├── services/api.js    # Backend API client
│   │   ├── App.jsx
│   │   └── main.jsx
│   ├── index.html
│   ├── vite.config.js
│   └── package.json
├── backend/
│   ├── main.py                # FastAPI entry point
│   ├── agents/                # Restaurant finder, qualifier, outreach agents
│   ├── services/              # Discovery, website check, email, Claude API
│   ├── models/                # Database models & connection
│   ├── schemas/               # Pydantic API schemas
│   ├── prompts/               # AI prompt templates
│   ├── tests/
│   └── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## Setup

### 1. Clone & configure environment

```bash
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

### 2. Backend

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Frontend

```bash
cd frontend
npm install
```

## Running

### Backend (run from inside `backend/`)

```bash
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend (from `frontend/` directory)

```bash
cd frontend
npm run dev
```

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- API docs (Swagger): http://localhost:8000/docs
- Health check: http://localhost:8000/health

## API Endpoints

| Method | Path      | Description      |
|--------|-----------|------------------|
| GET    | /health   | Health check     |
| GET    | /docs     | Swagger UI       |

## Development Notes

- The Vite dev server proxies `/api/*` → `http://localhost:8000/*`, so the frontend never exposes the backend URL.
- Never commit `.env`; use `.env.example` as a template.
- AI agents, scraping, and email sending are scaffolded but not yet implemented.
