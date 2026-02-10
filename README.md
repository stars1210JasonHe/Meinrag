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
```

4. **Set up the frontend**
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
│   ├── config.py                 # Configuration settings
│   ├── dependencies.py           # Dependency injection
│   ├── main.py                   # FastAPI application
│   ├── llm/                      # LLM provider integration
│   ├── models/                   # Data models and schemas
│   ├── rag/                      # RAG pipeline (chain, prompts, memory)
│   ├── routers/                  # API endpoints
│   ├── services/                 # Business logic (document processing, AI suggestions)
│   └── vectorstore/              # Vector store implementations
├── frontend/                     # React frontend
│   ├── src/
│   │   ├── App.jsx               # Main React component
│   │   ├── App.css               # Application styles
│   │   └── main.jsx              # Entry point
│   └── package.json
├── data/                         # Document storage
├── chroma_db/                    # ChromaDB persistence
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

# Vector Store
VECTOR_STORE=chroma              # or faiss

# Features
HYBRID_SEARCH_ENABLED=false      # Enable BM25+Vector fusion
RERANK_ENABLED=false             # Enable LLM re-ranking
MEMORY_TTL_SECONDS=3600          # Chat session timeout
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

### Documents
- `POST /documents/upload` - Upload document (optional: `?collection=name&auto_suggest=true`)
- `GET /documents` - List all documents (optional: `?collection=name`)
- `DELETE /documents/{doc_id}` - Delete document

### Query
- `POST /query` - Ask a question
  ```json
  {
    "question": "What is this about?",
    "collection": "legal",
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
# Test collections feature
uv run python test_collections.py

# Test chatbot features
uv run python test_chatbot.py
```

### Code Structure

- **Modular Design**: Separate concerns (routing, business logic, data access)
- **Dependency Injection**: Clean testable code with FastAPI's `Depends()`
- **Abstract Interfaces**: Swap vector stores via `VectorStoreManager` ABC
- **Type Safety**: Full type hints with Pydantic models

---

## Documentation

- **[HOW_TO_RUN.md](HOW_TO_RUN.md)** - Complete setup and testing guide
- **[CLAUDE.md](CLAUDE.md)** - Architecture and development patterns
- **[COLLECTIONS_SUMMARY.md](COLLECTIONS_SUMMARY.md)** - Collections feature documentation
- **[QUICK_START_COLLECTIONS.md](QUICK_START_COLLECTIONS.md)** - API usage examples
- **[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)** - Technical implementation details
- **[ROADMAP.md](ROADMAP.md)** - Development phases and features

---

## Features Roadmap

### Completed ✅
- [x] Basic RAG pipeline with FastAPI
- [x] Document upload and processing
- [x] Vector similarity search
- [x] Collections organization
- [x] AI auto-categorization
- [x] Hybrid search (BM25 + Vector)
- [x] LLM re-ranking
- [x] Chat memory
- [x] React frontend
- [x] Multi-language support (EN/中文)

### Planned 🔮
- [ ] User authentication
- [ ] Multi-user support
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
