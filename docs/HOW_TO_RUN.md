# 🚀 How to Run MEINRAG (Frontend + Backend)

Complete guide to test your chatbot with collections feature.

---

## Prerequisites

✅ Python 3.12+ with `uv` installed
✅ Node.js 18+ with `npm` installed
✅ OpenAI API key in `.env` file

---

## Step 1: Start Backend

Open **Terminal 1**:

```bash
cd E:\MEINRAG
uv run uvicorn app.main:app --reload
```

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
INFO:     MEINRAG started | LLM=openai | VectorStore=chroma | Documents=0
```

✅ **Backend running at:** `http://localhost:8000`

---

## Step 2: Start Frontend

Open **Terminal 2** (keep Terminal 1 running):

```bash
cd E:\MEINRAG\frontend
npm run dev
```

You should see:
```
  VITE v5.x.x  ready in xxx ms

  ➜  Local:   http://localhost:5173/
  ➜  Network: use --host to expose
```

✅ **Frontend running at:** `http://localhost:5173`

---

## Step 3: Open Browser

Navigate to: **http://localhost:5173**

You should see the welcome screen:
```
Welcome to MEINRAG! 👋
Upload documents and ask questions in English or Chinese (中文)
```

---

## Step 4: Test Upload (Manual Collection)

### 4.1 Upload a Document

1. Click **"📤 Upload"** button (bottom of sidebar)
2. Select a PDF file (e.g., contract, report, manual)
3. Document appears in sidebar after upload
4. System message shows: `✅ Uploaded: filename.pdf`

### 4.2 Upload to Specific Collection

1. First, create a custom collection by uploading with AI suggest
2. OR just type collection name in future (not in current UI - manually via curl):

```bash
curl -X POST "http://localhost:8000/documents/upload?collection=law" \
  -F "file=@E:\MEINRAG\data\test_chatbot\contract.pdf"
```

---

## Step 5: Test AI Auto-Suggest

1. Click **"✨ AI Suggest"** button
2. Select a document (PDF, DOCX, etc.)
3. Wait ~2 seconds for AI to analyze
4. System message shows:
   ```
   ✅ Uploaded: contract.pdf (AI suggested: legal) → Collection: legal
   ```
5. Collection appears in sidebar automatically!

---

## Step 6: Test Chat (English)

1. Type in input box: **"What is this document about?"**
2. Press **Enter** or click **Send** button
3. AI responds with answer and sources:
   ```
   🤖 This document is an employment contract...

   📎 Sources:
   • contract.pdf (chunk 0)
   ```

---

## Step 7: Test Chat (Chinese - 中文)

1. Type: **"这个文档讲的是什么?"**
2. Press Enter
3. AI responds in Chinese:
   ```
   🤖 这份文件是一份雇佣合同...
   ```

✅ **Language auto-detection works!**

---

## Step 8: Test Collections Filtering

### 8.1 Upload Multiple Documents

```bash
# Upload to "law" collection
curl -X POST "http://localhost:8000/documents/upload?collection=law" \
  -F "file=@contract.pdf"

# Upload to "medical" collection
curl -X POST "http://localhost:8000/documents/upload?collection=medical" \
  -F "file=@report.pdf"
```

### 8.2 Filter by Collection

1. **Sidebar** now shows:
   ```
   📁 law (1)
   📁 medical (1)
   ```
2. Click **"📁 law"**
3. Document list shows only law documents
4. Input placeholder changes: `"Ask about law documents..."`
5. Ask question: **"What are the terms?"**
6. Results **only from law documents**

### 8.3 View All Documents

1. Click **"All Documents"** at top of Collections
2. Shows all documents regardless of collection
3. Queries search across all documents

---

## Step 9: Test Chat Memory

1. Ask: **"What is the notice period?"**
2. AI responds: *"30 days according to the contract"*
3. Ask follow-up: **"Can you explain that more?"**
4. AI remembers context and elaborates

✅ **Session memory works!**

---

## Step 10: Test Document Management

### Delete Document

1. Hover over document in sidebar
2. Click **🗑️ (trash icon)**
3. Document removed
4. System message: `🗑️ Deleted document: abc123`

---

## Common Issues & Fixes

### Issue 1: Backend Not Starting

**Error**: `ModuleNotFoundError` or import errors

**Fix**:
```bash
cd E:\MEINRAG
uv sync
uv run uvicorn app.main:app --reload
```

### Issue 2: Frontend Shows Connection Error

**Error**: "Failed to fetch documents"

**Fix**:
1. Check backend is running: `curl http://localhost:8000/health`
2. Check browser console (F12) for CORS errors
3. Verify API_BASE in `frontend/src/App.jsx` is `http://localhost:8000`

### Issue 3: Upload Fails

**Error**: `Upload failed: 400`

**Fix**:
- Check file extension is supported (.pdf, .docx, .txt, .md, .html, .xlsx, .pptx)
- Check backend logs for error details

### Issue 4: AI Suggest Doesn't Work

**Error**: No suggestion shown

**Fix**:
1. Check `OPENAI_API_KEY` in `.env`
2. Check backend logs for API errors
3. Verify internet connection

### Issue 5: Chinese Characters Display Wrong

**Problem**: 中文显示为乱码

**Fix**:
1. Ensure `.env` uses UTF-8 encoding
2. Reload page (Ctrl+R)
3. Check browser encoding settings

---

## API Endpoints You Can Test

### Health Check
```bash
curl http://localhost:8000/health
```

### List Documents
```bash
curl http://localhost:8000/documents
```

### List by Collection
```bash
curl "http://localhost:8000/documents?collection=law"
```

### Upload with Collection
```bash
curl -X POST "http://localhost:8000/documents/upload?collection=law" \
  -F "file=@contract.pdf"
```

### Upload with AI Suggest
```bash
curl -X POST "http://localhost:8000/documents/upload?auto_suggest=true" \
  -F "file=@report.pdf"
```

### Query
```bash
curl -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is this about?",
    "collection": "law",
    "session_id": "test123",
    "top_k": 4
  }'
```

### Delete Document
```bash
curl -X DELETE "http://localhost:8000/documents/abc123"
```

---

## Advanced Features

### Enable Hybrid Search

Edit `.env`:
```
HYBRID_SEARCH_ENABLED=true
HYBRID_BM25_WEIGHT=0.5
```

Restart backend. Queries now use BM25+vector fusion.

### Enable Re-ranking

Edit `.env`:
```
RERANK_ENABLED=true
RERANK_TOP_N=3
```

Restart backend. Queries use LLM re-ranking (slower but more accurate).

---

## Keyboard Shortcuts

### Frontend
- **Enter** - Send message
- **Ctrl+R** - Reload page

### Backend
- **Ctrl+C** - Stop server

---

## Development Workflow

### Make Changes to Backend

1. Edit Python files in `app/`
2. Server auto-reloads (uvicorn --reload)
3. Test API via frontend or curl

### Make Changes to Frontend

1. Edit `frontend/src/App.jsx` or `App.css`
2. Browser auto-reloads (Vite HMR)
3. See changes instantly

---

## Production Deployment

### Backend (FastAPI)

```bash
# Install production server
pip install gunicorn

# Run with gunicorn
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
```

### Frontend (React)

```bash
cd frontend
npm run build

# Serve via FastAPI or nginx
```

---

## Next Steps

1. ✅ Test all features
2. ✅ Upload your own documents
3. ✅ Try Chinese and English queries
4. 📋 Customize UI colors (edit `App.css`)
5. 📋 Add authentication
6. 📋 Deploy to production

---

## Questions?

- **Backend docs**: See `COLLECTIONS_SUMMARY.md`
- **API examples**: See `QUICK_START_COLLECTIONS.md`
- **Frontend code**: See `frontend/src/App.jsx`
- **Architecture**: See `CLAUDE.md`

Enjoy your chatbot! 🎉
