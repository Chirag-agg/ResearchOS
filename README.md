# ResearchOS

ResearchOS is an open-source, local-first research operating system. Unlike traditional research agents that run in a black box, ResearchOS is designed to expose every discrete step of the research pipeline—from query planning to search, content scraping, fact extraction, and report verification.

This architecture prioritizes total transparency, traceability (linking claims back to specific URLs and generated queries), and offline execution.

---

## Technical Stack (V1 Backend)
* **Python 3.12+**
* **FastAPI** — Async REST API framework
* **SQLModel** — Combined SQLAlchemy & Pydantic ORM
* **SQLite** — Local-first transactional database
* **Ollama** — Local LLM runner (llama3 / mistral)
* **SearXNG** — Self-hosted privacy-focused search engine
* **Playwright & Trafilatura** — Dynamic browser automation & content extraction

---

## Project Structure

The project follows a **Clean Architecture / Service-Oriented** structure to ensure modularity and separation of concerns:

```
app/
├── core/
│   ├── config.py             # Settings using Pydantic Settings
│   └── db.py                 # SQLite SQLModel engine and DB session setup
├── models/
│   ├── base.py               # Database base utilities
│   ├── research.py           # Planner DTO schemas (ResearchQuestion/Queries)
│   └── session.py            # ResearchSession database entities & schemas
├── repositories/
│   └── session.py            # Session CRUD operations
├── services/
│   └── planner.py            # Ollama query planning service
├── api/
│   ├── deps.py               # Dependency Injection providers
│   └── v1/
│       ├── router.py         # Registers API V1 routes
│       └── endpoints/
│           ├── health.py     # Heartbeat status endpoint
│           ├── research.py   # Planner endpoint
│           └── sessions.py   # Research Session CRUD endpoints
├── main.py                   # FastAPI Application Entrypoint
tests/                        # Automated unit & integration tests
pytest.ini                    # Pytest configuration
requirements.txt              # Production and development dependencies
.env                          # Local environment variables
.gitignore                    # Version control ignore rules
```

---

## Local Setup

### 1. Clone & Setup Environment
Ensure Python 3.12+ is installed. Create a virtual environment and install the package requirements:

```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
# On Linux / macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Create a local `.env` file at the root directory (this is excluded from git):
```env
PROJECT_NAME="ResearchOS"
API_V1_STR="/api/v1"
DATABASE_URL="sqlite+aiosqlite:///./research_os.db"
OLLAMA_API_URL="http://localhost:11434"
LLM_MODEL="llama3"
```

### 3. Run Automated Tests
Execute the pytest suite using `pytest-asyncio`:
```bash
python -m pytest
```

---

## Running the API Server

Launch the development server using Uvicorn:

```bash
uvicorn app.main:app --reload
```

### Interactive API Documentation
Once the server is running, visit:
* Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
* ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## API Documentation Quick Reference

### 1. Health Checks
* **GET** `/health` (or `/api/v1/health`)
  * Returns core API health: `{"status": "healthy"}`
* **GET** `/api/v1/health/llm`
  * Checks if local Ollama model is online.

### 2. Session Management
* **POST** `/api/v1/sessions`
  * **Payload:** `{"question": "Best vector databases for RAG"}`
  * Initializes a session tracking database record.
* **GET** `/api/v1/sessions`
  * Lists all sessions.
* **GET** `/api/v1/sessions/{session_id}/events`
  * Retrieves a chronological history of EventBus pipeline events published for the session.

### 3. Core Research Pipeline Endpoints

#### Phase 1: Query Generation
* **POST** `/research`
  * **Payload:** `{"question": "Best vector databases for RAG"}`
  * Converts the question into optimized search queries via local Ollama.

#### Phase 2: Search (SearXNG)
* **POST** `/research/search`
  * **Payload:** `{"question": "Best vector databases for RAG"}`
  * Runs generated queries through SearXNG, deduplicates URL search results, and saves them.

#### Phase 3: Scrape & Extract (Playwright + Trafilatura)
* **POST** `/research/fetch`
  * **Payload:** `{"session_id": "<session-uuid>"}`
  * Opens unique URLs concurrently using Chromium tabs, extracts clean text, saves raw HTML, and scores extraction quality.

#### Phase 4: Claim Extraction
* **POST** `/api/v1/research/claims`
  * **Payload:** `{"session_id": "<session-uuid>"}`
  * Chunks text into 4000 char blocks, extracts factual claims using Ollama, hashes claims to prevent duplicates, and links to source queries and chunks.
