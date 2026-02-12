# MEINRAG

**Your intelligent document assistant powered by RAG (Retrieval-Augmented Generation)**

MEINRAG is a full-stack application that allows you to upload documents, organize them into collections, and ask questions in natural language. Get accurate answers with source citations from your document library.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.12+-blue.svg)
![React](https://img.shields.io/badge/react-18+-blue.svg)

---

## Features

### Core Capabilities
- **Multi-language Support**: Ask questions in English or Chinese (中文)
- **Smart Collections**: Organize documents by topic or category
- **AI Auto-Categorization**: Let AI suggest collection names based on document content
- **Contextual Conversations**: Ask follow-up questions with chat memory
- **Source Citations**: Every answer includes references to source documents
- **Multiple Document Formats**: PDF, DOCX, TXT, MD, HTML, XLSX, PPTX

### Advanced Features
- **Hybrid Search**: Combines semantic vector search with BM25 keyword matching
- **LLM Re-ranking**: Improves result quality using language model scoring
- **Document Filtering**: Query specific documents or collections
- **Session Management**: Maintains conversation context per user
- **Flexible Vector Stores**: Support for ChromaDB and FAISS

---

## Tech Stack

### Backend
- **Framework**: FastAPI
- **Database**: PostgreSQL 16 (via Docker) + SQLAlchemy 2.0 async
- **Migrations**: Alembic
- **LLM Integration**: LangChain with OpenAI/OpenRouter
- **Vector Stores**: ChromaDB, FAISS
- **Embeddings**: OpenAI text-embedding-3-small
- **Document Processing**: PyPDF2, python-docx, BeautifulSoup4, openpyxl, python-pptx

### Frontend
- **Framework**: React 18 with Vite
- **HTTP Client**: Axios
- **Icons**: Lucide React
- **Styling**: Custom CSS

---

## Quick Start

### Prerequisites
- Python 3.12+
- Node.js 18+
- Docker Desktop (for PostgreSQL)
- OpenAI API key

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/stars1210JasonHe/Meinrag.git
cd Meinrag
```

2. **Set up the backend**
```bash
# Install uv (Python package manager)
pip install uv

# Install dependencies
uv sync

# Create .env file
cp .env.example .env
```

3. **Configure environment variables**
Edit `.env` and add your API key:
```env
OPENAI_API_KEY=your-api-key-here
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/meinrag
```

4. **Start PostgreSQL**
```bash
docker compose up -d
```

5. **Run database migrations**
```bash
uv run alembic upgrade head
```

6. **Set up the frontend**
```bash
cd frontend
npm install
```

### Running the Application

**Terminal 1 - Start Backend:**
```bash
uv run uvicorn app.main:app --reload
```
Backend runs at: http://localhost:8000

**Terminal 2 - Start Frontend:**
```bash
cd frontend
npm run dev
```
Frontend runs at: http://localhost:5173

---

## Usage

### Upload Documents

1. Click **"Upload Document"** in the sidebar
2. Select a file (PDF, DOCX, TXT, etc.)
3. Document is processed and indexed automatically

### Use AI Auto-Categorization

1. Click **"Auto-Categorize"** button
2. Select a file
3. AI analyzes content and suggests a collection name
4. Document is automatically organized

### Ask Questions

1. Type your question in the input box
2. Press Enter or click Send
3. Get an answer with source citations

### Filter by Collection

1. Collections appear in the sidebar after uploading
2. Click a collection name to filter documents
3. Questions will only search within that collection

---

## Project Structure

```
MEINRAG/
├── app/                          # Backend application
│   ├── config.py                 # Configuration (Pydantic Settings)
│   ├── dependencies.py           # FastAPI dependency injection
│   ├── main.py                   # FastAPI app + lifespan
│   ├── db/                       # Database layer
│   │   ├── models.py             # SQLAlchemy ORM models (5 tables)
│   │   ├── session.py            # Engine + async session factory
│   │   └── repositories.py       # DocumentRepository, UserRepository, ChatSessionRepository
│   ├── llm/                      # LLM provider integration
│   ├── models/                   # Pydantic schemas
│   ├── rag/                      # RAG pipeline (chain, prompts)
│   ├── routers/                  # API endpoints
│   ├── services/                 # Business logic (document processing, AI suggestions)
│   └── vectorstore/              # Vector store implementations
├── alembic/                      # Database migrations
├── frontend/                     # React frontend
│   ├── src/
│   │   ├── App.jsx               # Main React component
│   │   ├── App.css               # Application styles
│   │   └── main.jsx              # Entry point
│   └── package.json
├── scripts/                      # Utility scripts
│   └── migrate_json_to_pg.py     # One-time JSON -> PostgreSQL migration
├── data/                         # Uploaded files + vector store
├── docker-compose.yml            # PostgreSQL 16 container
├── alembic.ini                   # Alembic config
├── .env                          # Environment variables
├── pyproject.toml                # Python dependencies
└── README.md
```

---

## Configuration

### Environment Variables

Key settings in `.env`:

```env
# LLM Provider
LLM_PROVIDER=openai              # or openrouter
OPENAI_API_KEY=your-key
OPENAI_MODEL=gpt-4o-mini

# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/meinrag

# Vector Store
VECTOR_STORE=chroma              # or faiss

# Features
HYBRID_SEARCH_ENABLED=false      # Enable BM25+Vector fusion
RERANK_ENABLED=false             # Enable LLM re-ranking
MEMORY_SESSION_TTL=3600          # Chat session timeout (seconds)
```

### Advanced Features

**Enable Hybrid Search:**
```env
HYBRID_SEARCH_ENABLED=true
HYBRID_BM25_WEIGHT=0.5
```

**Enable Re-ranking:**
```env
RERANK_ENABLED=true
RERANK_TOP_N=3
```

---

## API Endpoints

### Users
- `GET /users` - List all users
- `POST /users` - Create a user
- `GET /users/current` - Get current user (from `X-User-Id` header)

### Documents
- `POST /documents/upload` - Upload document (optional: `?collections=name1,name2&auto_suggest=true`)
- `GET /documents` - List all documents (optional: `?collection=name`)
- `GET /documents/collections` - List all collections + taxonomy categories
- `GET /documents/{doc_id}/download` - Download original file
- `PATCH /documents/{doc_id}` - Update document collections
- `POST /documents/{doc_id}/reclassify` - AI reclassify document
- `DELETE /documents/{doc_id}` - Delete document

### Query
- `POST /query` - Ask a question
  ```json
  {
    "question": "What is this about?",
    "collection": "legal-compliance",
    "session_id": "user123",
    "top_k": 4
  }
  ```

### Health
- `GET /health` - Check system status

---

## Development

### Run Tests

```bash
# Run all offline tests (no API key or PostgreSQL needed)
uv run pytest tests/ --ignore=tests/test_frontend_e2e.py --ignore=tests/test_api_workflow.py -v

# Run online API workflow tests (requires OPENAI_API_KEY)
uv run pytest tests/test_api_workflow.py -v

# Run frontend E2E tests (requires backend + frontend servers running)
uv run pytest tests/test_frontend_e2e.py -v -s
```

Tests use in-memory SQLite automatically — no PostgreSQL needed to run the test suite.

### Code Structure

- **Modular Design**: Separate concerns (routing, business logic, data access)
- **Dependency Injection**: Clean testable code with FastAPI's `Depends()`
- **Abstract Interfaces**: Swap vector stores via `VectorStoreManager` ABC
- **Type Safety**: Full type hints with Pydantic models

---

## Documentation

- **[HOW_TO_RUN.md](docs/HOW_TO_RUN.md)** - Complete setup and testing guide
- **[CLAUDE.md](CLAUDE.md)** - Architecture and development patterns
- **[COLLECTIONS_SUMMARY.md](docs/COLLECTIONS_SUMMARY.md)** - Collections feature documentation
- **[QUICK_START_COLLECTIONS.md](docs/QUICK_START_COLLECTIONS.md)** - API usage examples
- **[IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md)** - Technical implementation details
- **[ROADMAP.md](docs/ROADMAP.md)** - Development phases and features

---

## Features Roadmap

### Completed
- [x] Basic RAG pipeline with FastAPI
- [x] Document upload and processing
- [x] Vector similarity search
- [x] Collections organization with taxonomy
- [x] AI auto-categorization
- [x] Hybrid search (BM25 + Vector)
- [x] LLM re-ranking
- [x] Persistent chat memory (PostgreSQL)
- [x] Multi-user support with isolation
- [x] PostgreSQL database (SQLAlchemy async)
- [x] React frontend
- [x] Multi-language support (EN)

### Planned
- [ ] Page numbers in source citations
- [ ] User authentication (login/password)
- [ ] Document versioning
- [ ] Advanced analytics
- [ ] Export conversation history
- [ ] Mobile responsive design improvements

---

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## License

This project is licensed under the MIT License.

---

## Acknowledgments

- Built with [LangChain](https://www.langchain.com/)
- Vector stores: [ChromaDB](https://www.trychroma.com/), [FAISS](https://github.com/facebookresearch/faiss)
- LLM providers: [OpenAI](https://openai.com/), [OpenRouter](https://openrouter.ai/)
- Frontend: [React](https://react.dev/), [Vite](https://vitejs.dev/)

---

## Support

For questions or issues, please open an issue on GitHub.

**Repository**: https://github.com/stars1210JasonHe/Meinrag
