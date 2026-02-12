# Quick Start: Collections Feature

Get started with collections in 5 minutes!

---

## 1. Start the Server

```bash
cd E:\MEINRAG
uv run uvicorn app.main:app --reload
```

Server runs at: `http://localhost:8000`

---

## 2. Upload Documents

### Option A: Manual Collection

```bash
# Upload a legal document
curl -X POST "http://localhost:8000/documents/upload?collection=law" \
  -F "file=@contract.pdf"

# Upload a medical document
curl -X POST "http://localhost:8000/documents/upload?collection=medical" \
  -F "file=@patient_report.pdf"
```

### Option B: AI Auto-Suggest

```bash
# Let AI suggest the collection
curl -X POST "http://localhost:8000/documents/upload?auto_suggest=true" \
  -F "file=@contract.pdf"

# AI analyzes content and suggests "legal" or "employment-agreement"
```

---

## 3. List Documents

### All Documents
```bash
curl http://localhost:8000/documents
```

### Filter by Collection
```bash
# Only legal documents
curl "http://localhost:8000/documents?collection=law"

# Only medical documents
curl "http://localhost:8000/documents?collection=medical"
```

---

## 4. Query Documents

### Search All Collections
```bash
curl -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is covered in these documents?",
    "top_k": 4
  }'
```

### Search Specific Collection
```bash
curl -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What are the termination clauses?",
    "collection": "law",
    "top_k": 4
  }'
```

### Search with Multiple Filters
```bash
curl -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What does section 5 say?",
    "collection": "law",
    "doc_ids": ["abc123"],
    "top_k": 3
  }'
```

### Chat with Memory + Collection
```bash
# First question
curl -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What is the notice period?",
    "collection": "law",
    "session_id": "user1"
  }'

# Follow-up (remembers context)
curl -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Can you explain that in more detail?",
    "collection": "law",
    "session_id": "user1"
  }'
```

---

## 5. Python Examples

### Upload with Collection

```python
import requests

url = "http://localhost:8000/documents/upload"

# Manual collection
with open("contract.pdf", "rb") as f:
    response = requests.post(
        url,
        params={"collection": "law"},
        files={"file": f}
    )
    print(response.json())

# AI auto-suggest
with open("report.pdf", "rb") as f:
    response = requests.post(
        url,
        params={"auto_suggest": True},
        files={"file": f}
    )
    result = response.json()
    print(f"Suggested: {result['suggested_collection']}")
    print(f"Assigned: {result['collection']}")
```

### Query with Collection

```python
import requests

url = "http://localhost:8000/query"

# Query specific collection
response = requests.post(url, json={
    "question": "What are the key terms?",
    "collection": "law",
    "top_k": 5
})

result = response.json()
print(f"Answer: {result['answer']}")
print(f"\nSources from collection '{result.get('collection', 'all')}':")
for i, source in enumerate(result['sources'], 1):
    print(f"  {i}. {source['source_file']}")
```

### List Documents by Collection

```python
import requests

# Get all law documents
response = requests.get(
    "http://localhost:8000/documents",
    params={"collection": "law"}
)

docs = response.json()
print(f"Found {docs['total']} law documents:")
for doc in docs['documents']:
    print(f"  - {doc['filename']} ({doc['chunk_count']} chunks)")
```

---

## 6. JavaScript/Fetch Examples

### Upload with Auto-Suggest

```javascript
const formData = new FormData();
formData.append('file', fileInput.files[0]);

const response = await fetch(
  'http://localhost:8000/documents/upload?auto_suggest=true',
  {
    method: 'POST',
    body: formData
  }
);

const result = await response.json();
console.log('AI suggested:', result.suggested_collection);
console.log('Assigned to:', result.collection);
```

### Query with Collection

```javascript
const response = await fetch('http://localhost:8000/query', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    question: 'What are the requirements?',
    collection: 'technical',
    top_k: 4
  })
});

const result = await response.json();
console.log('Answer:', result.answer);
console.log('Sources:', result.sources.map(s => s.source_file));
```

---

## 7. Advanced Features

### Enable Hybrid Search + Collection
```json
{
  "question": "contract termination 30 days",
  "collection": "law",
  "top_k": 5
}
```

Set in `.env`:
```
HYBRID_SEARCH_ENABLED=true
HYBRID_BM25_WEIGHT=0.5
```

### Enable Re-ranking + Collection
```json
{
  "question": "What are the most important clauses?",
  "collection": "law",
  "top_k": 3
}
```

Set in `.env`:
```
RERANK_ENABLED=true
RERANK_TOP_N=3
```

### All Features Combined
```json
{
  "question": "What did we discuss about termination?",
  "collection": "law",
  "doc_ids": ["contract_abc"],
  "session_id": "user1",
  "top_k": 4
}
```

With `.env`:
```
HYBRID_SEARCH_ENABLED=true
RERANK_ENABLED=true
```

---

## 8. Common Patterns

### Pattern 1: Organized Knowledge Base

```bash
# Create collections for different domains
POST /documents/upload?collection=legal
POST /documents/upload?collection=hr
POST /documents/upload?collection=technical
POST /documents/upload?collection=marketing

# Users query their domain
POST /query { "question": "...", "collection": "technical" }
```

### Pattern 2: Let AI Organize

```bash
# Upload everything with AI
POST /documents/upload?auto_suggest=true  # → "legal"
POST /documents/upload?auto_suggest=true  # → "financial"
POST /documents/upload?auto_suggest=true  # → "hr-policies"

# AI automatically organizes your documents
```

### Pattern 3: Project-Based Collections

```bash
# Use project names as collections
POST /documents/upload?collection=project-alpha
POST /documents/upload?collection=project-beta
POST /documents/upload?collection=archived-2023

# Query by project
POST /query { "question": "...", "collection": "project-alpha" }
```

### Pattern 4: Time-Based Collections

```bash
# Organize by time period
POST /documents/upload?collection=q1-2024
POST /documents/upload?collection=q2-2024

# Query specific quarter
POST /query { "question": "...", "collection": "q1-2024" }
```

---

## 9. Tips & Best Practices

### Collection Naming
✅ **Good**: `law`, `medical-reports`, `tech-docs`, `q1-2024`
❌ **Avoid**: `Law`, `medical Reports`, `Tech!Docs`, spaces

### When to Use Collections
- **YES**: Different document types (legal, medical, technical)
- **YES**: Different projects or teams
- **YES**: Different time periods
- **NO**: If all documents are the same type

### When to Use AI Suggest
- **YES**: Unsure about categorization
- **YES**: Large batch uploads
- **YES**: Diverse document types
- **NO**: If you have strict naming conventions

### Performance Tips
- Collections don't slow down queries (same speed as no filter)
- AI suggestion adds ~1-2 seconds to upload
- Hybrid search + collection works great together
- Re-ranking + collection is slightly slower but more accurate

---

## 10. Troubleshooting

### Issue: Upload without collection

**Problem**: Document uploaded but no collection assigned

**Solution**: This is normal! Documents work fine without collections:
```bash
# Upload without collection
POST /documents/upload
# Document added with collection=null
# Still searchable in queries without collection filter
```

### Issue: AI suggests unexpected name

**Problem**: AI suggests "general" or odd name

**Solution**: Override with manual collection:
```bash
# Manual collection takes priority
POST /documents/upload?collection=my-category&auto_suggest=true
# Uses "my-category", ignores AI suggestion
```

### Issue: Query returns no results

**Problem**: Query with collection returns empty

**Solution**: Check collection name exactly matches:
```bash
# Wrong: collection="Law" (capital L)
# Right: collection="law" (lowercase)
```

### Issue: Can't see collection in list

**Problem**: Document uploaded but not in collection list

**Solution**: Check spelling and case:
```bash
GET /documents?collection=law  # Exact match required
```

---

## 11. Next Steps

1. **Test it**: Run `uv run python test_collections.py`
2. **Try it**: Upload some PDFs and query them
3. **Build frontend**: See `FRONTEND_DESIGN.md` for UI ideas
4. **Read docs**: Check `COLLECTIONS_SUMMARY.md` for details

---

## Questions?

- **Full implementation**: See `IMPLEMENTATION_PLAN.md`
- **Architecture**: See `CLAUDE.md`
- **Roadmap**: See `ROADMAP.md`
- **Frontend design**: See `FRONTEND_DESIGN.md`

Happy coding! 🚀
