# MEINRAG Frontend Design Guide

## Overview
Single-page chat interface with document management sidebar.

---

## ASCII Layout

```
┌────────────────────────────────────────────────────────────────────────────┐
│  MEINRAG - Document Chat Assistant                          [Settings] [?] │
├────────────────┬───────────────────────────────────────────────────────────┤
│                │                                                            │
│  📁 COLLECTIONS│  💬 Chat Window                                           │
│                │  ┌──────────────────────────────────────────────────────┐ │
│  All Documents │  │ 🤖 Hi! Upload documents and ask me questions.        │ │
│  ────────────  │  └──────────────────────────────────────────────────────┘ │
│  ⚖️  Law (5)   │                                                            │
│  🏥 Medical (3)│  ┌──────────────────────────────────────────────────────┐ │
│  ⚙️  Tech (12) │  │ 👤 What are the termination clauses?                │ │
│  💼 Financial  │  └──────────────────────────────────────────────────────┘ │
│  + Add New     │                                                            │
│                │  ┌──────────────────────────────────────────────────────┐ │
│  ────────────  │  │ 🤖 Based on the contract documents:                  │ │
│  📄 DOCUMENTS  │  │                                                       │ │
│                │  │ The termination clauses include:                     │ │
│  🔍 [Search]   │  │ 1. 30-day written notice...                          │ │
│                │  │ 2. Material breach provisions...                     │ │
│  contract.pdf  │  │                                                       │ │
│  └ Law         │  │ 📎 Sources: contract.pdf (p.5), agreement.docx       │ │
│  report.docx   │  └──────────────────────────────────────────────────────┘ │
│  └ Medical     │                                                            │
│  manual.pdf    │  ┌──────────────────────────────────────────────────────┐ │
│  └ Tech        │  │ 👤 [Type your question...]                  [Send 📤]│ │
│                │  └──────────────────────────────────────────────────────┘ │
│  [Upload File] │                                                            │
│                │  ☑️ Search in: Law  ☐ Hybrid Search  ☐ Re-rank          │
│                │                                                            │
├────────────────┴───────────────────────────────────────────────────────────┤
│  Status: Connected | 20 documents | Session: user1                         │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## Component Breakdown

### 1. Top Bar
```
┌────────────────────────────────────────────────────────────────┐
│  MEINRAG                                    [Settings] [Help] │
└────────────────────────────────────────────────────────────────┘
```
- Logo/Title
- Settings gear icon → opens config modal
- Help icon → shows keyboard shortcuts, API docs link

---

### 2. Left Sidebar (Collections & Documents)

#### Collections Panel
```
📁 COLLECTIONS
─────────────────
⭐ All Documents (20)      ← Default, shows everything
─────────────────
⚖️  Law (5)                ← Click to filter chat
🏥 Medical (3)
⚙️  Tech (12)
💼 Financial (0)
📚 Research (2)
─────────────────
+ Create Collection        ← Add new category
```

**Interactions:**
- Click collection → filters both chat and document list
- Right-click → Rename/Delete collection
- Drag document onto collection → move it

#### Documents Panel
```
📄 DOCUMENTS
─────────────────
🔍 [Search docs...]

📄 contract.pdf
   └ ⚖️  Law
   └ 📅 2024-02-10
   └ [View] [Delete]

📄 medical-report.docx
   └ 🏥 Medical
   └ 📅 2024-02-09
   └ [View] [Delete]

─────────────────
[📤 Upload File]
```

**Upload Modal:**
```
┌─────────────────────────────────────────┐
│  Upload Document                    [×] │
├─────────────────────────────────────────┤
│                                         │
│  📁 Drag file here or click to browse  │
│                                         │
│  Collection:                            │
│  ┌─────────────────────────────────┐   │
│  │ 🤖 Suggested: legal        [✓]  │   │ ← AI suggestion
│  └─────────────────────────────────┘   │
│                                         │
│  Or choose:                             │
│  [Law ▼] [Medical] [Tech] [Custom...]  │
│                                         │
│  ☑️ Auto-suggest collection             │
│                                         │
│  [Cancel]              [Upload]         │
└─────────────────────────────────────────┘
```

---

### 3. Main Chat Area

#### Message Types

**AI Message:**
```
┌────────────────────────────────────────────────────────┐
│ 🤖 Based on the documents in "Law" collection:         │
│                                                        │
│ The contract includes the following clauses:          │
│ 1. Termination with 30-day notice                     │
│ 2. Breach of contract penalties                       │
│                                                        │
│ 📎 Sources:                                            │
│    • contract.pdf (page 5, chunk 3)                   │
│    • agreement.docx (page 2, chunk 7)                 │
│                                                        │
│ 🕐 2:34 PM                                             │
└────────────────────────────────────────────────────────┘
```

**User Message:**
```
                          ┌─────────────────────────────┐
                          │ What are the clauses?   👤 │
                          │ 🕐 2:34 PM                  │
                          └─────────────────────────────┘
```

**System Message:**
```
         ┌───────────────────────────────────────┐
         │ ℹ️ Uploaded contract.pdf to "Law"     │
         └───────────────────────────────────────┘
```

#### Input Area
```
┌────────────────────────────────────────────────────────────────┐
│ 💬 [Type your question here...                      ] [Send 📤]│
└────────────────────────────────────────────────────────────────┘

Options bar:
☑️ Search in: Law ▼    ☐ Hybrid Search    ☐ Re-rank    [⚙️ More...]
```

**Expanded Options (⚙️ More):**
```
┌──────────────────────────────────────┐
│ Advanced Search Options              │
├──────────────────────────────────────┤
│ Collection: [Law ▼]                  │
│ Specific Docs: [Select...]           │
│ Results: [8] (1-20)                  │
│ ☐ Hybrid Search (BM25+Vector)       │
│ ☐ LLM Re-ranking (slower, better)   │
│ Session ID: user1                    │
└──────────────────────────────────────┘
```

---

### 4. Bottom Status Bar
```
┌────────────────────────────────────────────────────────────────┐
│ 🟢 Connected | 📊 20 docs | 🗂️ 5 collections | 👤 user1      │
└────────────────────────────────────────────────────────────────┘
```

---

## User Flows

### Flow 1: Upload Document
```
1. User clicks [Upload File]
2. Selects file (e.g., contract.pdf)
3. AI suggests: "legal" ← auto_suggest=true
4. User accepts or changes to "law"
5. Document uploads, shows in sidebar
6. Toast notification: "✓ Uploaded contract.pdf to Law"
```

### Flow 2: Ask Question (Simple)
```
1. User types: "What are the termination clauses?"
2. Clicks [Send]
3. System shows: "🤖 Searching..."
4. Response appears with sources
5. User can click source to view original doc
```

### Flow 3: Ask Question (Filtered)
```
1. User clicks "Law" collection in sidebar
2. Chat shows: "🔍 Searching only in: Law"
3. User types question
4. Results only from Law documents
5. Can clear filter by clicking "All Documents"
```

### Flow 4: Follow-up Question (Chat Memory)
```
1. User asks: "What is the notice period?"
2. AI responds: "30 days according to the contract"
3. User asks: "Can you explain that further?" ← uses session_id
4. AI remembers context, elaborates on 30-day notice
```

### Flow 5: Manage Collections
```
1. Right-click "Tech" collection
2. Menu: [Rename] [Delete] [Merge into...]
3. Select "Rename" → Input: "Technical"
4. All docs in "Tech" now show "Technical"
```

---

## API Calls (Frontend → Backend)

### Upload Document
```javascript
POST /documents/upload?collection=law&auto_suggest=true
Content-Type: multipart/form-data

FormData: { file: File }

Response:
{
  "doc_id": "abc123",
  "filename": "contract.pdf",
  "chunk_count": 42,
  "collection": "law",
  "suggested_collection": "legal",  // AI suggestion
  "message": "Document uploaded"
}
```

### List Documents
```javascript
GET /documents?collection=law

Response:
{
  "documents": [
    {
      "doc_id": "abc123",
      "filename": "contract.pdf",
      "file_type": ".pdf",
      "collection": "law",
      "chunk_count": 42,
      "uploaded_at": "2024-02-10T14:30:00Z"
    }
  ],
  "total": 1
}
```

### Query
```javascript
POST /query

Body:
{
  "question": "What are the termination clauses?",
  "collection": "law",           // Optional: filter by collection
  "doc_ids": ["abc123"],         // Optional: specific docs
  "session_id": "user1",         // For chat memory
  "top_k": 8                     // Number of results
}

Response:
{
  "answer": "The termination clauses include...",
  "sources": [
    {
      "content": "Either party may terminate...",
      "source_file": "contract.pdf",
      "chunk_index": 5
    }
  ],
  "question": "What are the termination clauses?",
  "session_id": "user1"
}
```

### Delete Document
```javascript
DELETE /documents/abc123

Response:
{
  "doc_id": "abc123",
  "message": "Document deleted successfully"
}
```

---

## Keyboard Shortcuts

```
Ctrl+K         → Focus search
Ctrl+U         → Upload file
Ctrl+Enter     → Send message
Ctrl+/         → Toggle sidebar
Esc            → Clear filters
Ctrl+1..5      → Switch collections
```

---

## Mobile Layout (Responsive)

```
┌──────────────────────────┐
│  MEINRAG        [☰]  [⚙️] │ ← Hamburger opens sidebar
├──────────────────────────┤
│                          │
│  💬 Chat                 │
│  ┌────────────────────┐  │
│  │ 🤖 Message         │  │
│  └────────────────────┘  │
│                          │
│  ┌────────────────────┐  │
│  │ 👤 Question        │  │
│  └────────────────────┘  │
│                          │
│  [Type...]      [Send]   │
│                          │
│  [📁 Collections ▼]      │ ← Collapsible on mobile
│  [📄 Documents]  [📤]     │
│                          │
└──────────────────────────┘
```

---

## Color Scheme (Suggestion)

```
Background:     #FFFFFF (light) / #1E1E1E (dark)
Primary:        #4F46E5 (Indigo)
Secondary:      #10B981 (Green)
AI Messages:    #F3F4F6 (Light Gray)
User Messages:  #4F46E5 (Indigo)
Collections:    #8B5CF6 (Purple icons)
Documents:      #6B7280 (Gray icons)
```

---

## Technology Stack (Recommendations)

### Option A: Simple (HTML/JS/CSS)
- Plain JavaScript + Fetch API
- No build step required
- Fast development
- Good for demo/prototype

### Option B: Modern (React/Vue)
- React + TypeScript
- Vite for bundling
- TailwindCSS for styling
- Better for production

### Option C: Full-Stack (Next.js)
- Next.js (React framework)
- Server-side rendering
- Best for production deployment

---

## State Management

```javascript
// Frontend State
{
  collections: [
    { name: "law", count: 5, icon: "⚖️" },
    { name: "medical", count: 3, icon: "🏥" }
  ],
  documents: [
    { id: "abc123", name: "contract.pdf", collection: "law" }
  ],
  messages: [
    { role: "user", content: "Question?", timestamp: "..." },
    { role: "assistant", content: "Answer.", sources: [...] }
  ],
  currentCollection: "law",  // Active filter
  sessionId: "user1",
  settings: {
    hybridSearch: false,
    rerank: false,
    topK: 8
  }
}
```

---

## Deployment

### Development
```bash
# Backend
cd E:\MEINRAG
uv run uvicorn app.main:app --reload

# Frontend (if using React)
cd frontend
npm run dev
```

### Production
```
Frontend → Build static files → Serve via FastAPI
OR
Frontend → Deploy to Vercel/Netlify → API calls to backend
```

---

## Next Steps

1. **Choose tech stack** (Option A/B/C above)
2. **Create `frontend/` directory** in project
3. **Start with simple HTML prototype**:
   - Chat window
   - File upload
   - Collection selector
4. **Iterate based on user feedback**
