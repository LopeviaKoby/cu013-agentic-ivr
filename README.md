# CU013 Conversational Backend v0.2.0

Conversational IT-support backend for CU013 and XCALLY Motion / Cally Square.

> **Notice**: V1 is reference material only and is not architecture to preserve. This repository is a clean, minimal reimplementation for v0.2.0.

## Overview

CU013 provides a natural, intelligent, and expected low-latency voice conversational agent for IT-support phone calls (VPN/VDI troubleshooting, account unlock, password reset).

- **LLM owns the conversation**: Natural-language understanding, multi-fact extraction, clarification, and conversation progression via Gemini.
- **Code owns what is legal and true**: Business truth, validation, side effects, authorization, and persistence.

## Tech Stack

- **Python 3.12**
- **FastAPI** + **Pydantic 2**
- **LangGraph** (StateGraph orchestration)
- **google-genai** (Vertex AI / Gemini 3.5 Flash-Lite)
- **Google Cloud Firestore** (Durable session store)
- **Cloud Run** / **Cloud Build** / **Artifact Registry**
- **pytest**, **Ruff**, **MyPy**, **Docker**

## Quick Start (Local Development)

### 1. Prerequisites

- Python 3.12 (`py -3.12` or `python3.12`)
- Google Cloud SDK (`gcloud`) with ADC configured

### 2. Environment Setup

```powershell
# Create virtual environment
py -3.12 -m venv .venv

# Activate (Windows PowerShell)
.\.venv\Scripts\Activate.ps1

# Activate (Linux/macOS)
# source .venv/bin/activate

# Upgrade pip and install package with dev dependencies
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

### 3. Configure Environment

Copy `.env.example` to `.env` and adjust if needed:

```powershell
Copy-Item .env.example .env
```

### 4. Run Locally

```powershell
uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

- Health check: `GET http://localhost:8080/health`
- Turn endpoint: `POST http://localhost:8080/turn`

### 5. Quality Gates

```powershell
# Linting & Formatting checks
python -m ruff check app tests
python -m ruff format --check app tests

# Type checking
python -m mypy app

# Unit tests
python -m pytest tests/ -v
```

## Docker

```powershell
# Build image
docker build -t cu013-agentic-ivr:latest .

# Run container
docker run -p 8080:8080 -e PORT=8080 cu013-agentic-ivr:latest
```

## Git Workflow

- **`main`**: Latest accepted release/baseline.
- **`dev`**: Active development branch. All work for Increment 1 is committed on `dev`.

## Documentation & Constitutional Rules

- [AGENTS.md](AGENTS.md) — Operational constitution and immutable baseline.
- [docs/NORTH_STAR.md](docs/NORTH_STAR.md) — North star vision and operational context.
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — Current v0.2.0 technical architecture.
- [docs/XCALLY_CONTRACT.md](docs/XCALLY_CONTRACT.md) — XCALLY / Cally Square integration contract.
- [docs/PROTOCOLS.md](docs/PROTOCOLS.md) — Domain IT-support protocol definitions.
- [docs/DEVELOPMENT_RULES.md](docs/DEVELOPMENT_RULES.md) — Development workflow, gates, and acceptance loop.
