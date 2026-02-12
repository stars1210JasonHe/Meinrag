# MEINRAG Upload Logic

## Overview

When a user uploads a file, the system processes it through 9 steps: validation, chunking, optional AI categorization, embedding, and storage.

---

## Upload Flow

```
User uploads file (e.g. contract.pdf)
         │
         ▼
1. POST /documents/upload
   ├── collection=law (optional)
   └── auto_suggest=true (optional)
         │
         ▼
2. Validate file type
   └── Reject if not in: .pdf, .docx, .txt, .md, .html, .xlsx, .pptx
         │
         ▼
3. Save to disk
   └── Generate doc_id (random 12-char hex)
   └── Save as: data/uploads/{doc_id}_{filename}
         │
         ▼
4. Chunk the document
   └── Load file based on type (PyPDF, python-docx, etc.)
   └── Split into chunks (default: 1000 chars, 200 overlap)
   └── Each chunk gets metadata: source_file, chunk_index
         │
         ▼
5. AI Suggest (only if auto_suggest=true AND no collection provided)
   └── Take first 3 chunks (~1500 chars)
   └── Send to LLM: "suggest a collection name"
   └── Return lowercase name (e.g. "legal", "ai-safety")
   └── Assign as collection
         │
         ▼
6. Tag chunks with metadata
   └── collection = "law" (or None)
   └── doc_id, source_file, chunk_index (already set)
         │
         ▼
7. Embed and store in vector store
   └── OpenAI text-embedding-3-small: each chunk → 1536-dim vector
   └── Vectors stored in ChromaDB/FAISS with metadata
         │
         ▼
8. Register in DocumentRegistry
   └── Save to data/metadata.json:
       { doc_id, filename, file_type, chunk_count, collection, uploaded_at }
         │
         ▼
9. Return response
   └── { doc_id, filename, chunk_count, collection, suggested_collection, message }
```

---

## What Gets Stored Where

| Data | Location | Purpose |
|------|----------|---------|
| Original file | `data/uploads/{doc_id}_{filename}` | Backup, can re-process later |
| Chunk text + vectors | ChromaDB (`data/vectorstore/`) | Similarity search at query time |
| Document metadata | `data/metadata.json` | Track uploads, collections, listing |

---

## Key Files Involved

| Step | File | Function |
|------|------|----------|
| 1-3 | `app/routers/documents.py` | `upload_document()` - endpoint handler |
| 4 | `app/services/document_processor.py` | `DocumentProcessor.load_and_split()` |
| 5 | `app/services/collection_suggester.py` | `suggest_collection()` |
| 7 | `app/vectorstore/chroma_store.py` | `ChromaStoreManager.add_documents()` |
| 8 | `app/models/document.py` | `DocumentRegistry.add()` |

---

## Chunking Details

- **Chunk size**: 1000 characters (configurable via `CHUNK_SIZE` in `.env`)
- **Overlap**: 200 characters (configurable via `CHUNK_OVERLAP` in `.env`)
- **Splitter**: LangChain `RecursiveCharacterTextSplitter`
- **Split order**: Tries `\n\n` → `\n` → ` ` → character-by-character

Example: A 5000-character document with 1000/200 settings produces roughly 6 chunks, where each chunk shares 200 characters with its neighbor for context continuity.

---

## Metadata Per Chunk

Each chunk stored in the vector store carries:

```json
{
  "source_file": "contract.pdf",
  "chunk_index": 3,
  "doc_id": "a1b2c3d4e5f6",
  "collection": "law"
}
```

This metadata enables:
- **doc_id filtering**: Query only chunks from specific documents
- **collection filtering**: Query only chunks in a collection (e.g. "law")
- **source citations**: Show which file and chunk an answer came from

---

## Query Flow (What Happens After Upload)

```
User asks: "What are the termination terms?"
         │
         ▼
1. Embed the question → 1536-dim vector
         │
         ▼
2. Search vector store for most similar chunks
   └── Apply filters: collection, doc_ids (if provided)
   └── Return top_k results (default: 4)
         │
         ▼
3. Build prompt: question + retrieved chunks as context
         │
         ▼
4. Send to LLM → Get answer
         │
         ▼
5. Return answer + source citations
```

The original file is never sent to the LLM. Only the relevant chunks (small pieces of text) are used as context.
