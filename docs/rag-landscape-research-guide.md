# RAG Landscape Research Guide

Use this guide to systematically evaluate each RAG project. For each project, fill in the evaluation template, then compile findings into a final comparison report.

---

## How to Use This Guide

1. Visit each project's GitHub repo + demo (if available)
2. Fill in the evaluation template for each
3. Try the quick-start install if time permits
4. Score each dimension 1-5 relative to MEINRAG
5. Write final report using the template at the bottom

---

## Projects to Research

| # | Project | GitHub | Demo/Docs | Category |
|---|---------|--------|-----------|----------|
| 1 | RAGFlow | https://github.com/infiniflow/ragflow | https://ragflow.io / https://cloud.ragflow.io | Full platform |
| 2 | Dify | https://github.com/langgenius/dify | https://dify.ai / https://cloud.dify.ai | Full platform |
| 3 | Open WebUI | https://github.com/open-webui/open-webui | https://openwebui.com | Chat UI + RAG |
| 4 | AnythingLLM | https://github.com/Mintplex-Labs/anything-llm | https://anythingllm.com | Privacy-first |
| 5 | PrivateGPT | https://github.com/zylon-ai/private-gpt | https://docs.privategpt.dev | Privacy-first |
| 6 | Kotaemon | https://github.com/Cinnamon/kotaemon | (Gradio UI, local only) | Research/citation |
| 7 | Onyx (Danswer) | https://github.com/onyx-dot-com/onyx | https://www.onyx.app | Enterprise search |
| 8 | LlamaIndex | https://github.com/run-llama/llama_index | https://docs.llamaindex.ai | Framework |
| 9 | Haystack | https://github.com/deepset-ai/haystack | https://haystack.deepset.ai | Framework |
| 10 | Verba | https://github.com/weaviate/Verba | (local only) | Weaviate showcase |
| 11 | Quivr | https://github.com/QuivrHQ/quivr | https://quivr.com | Library/platform |
| 12 | Mem0 | https://github.com/mem0ai/mem0 | https://mem0.ai | Memory layer |

---

## Evaluation Template (copy per project)

### Project: [Name]

**Basic Info**

| Field | Value |
|-------|-------|
| GitHub URL | |
| Stars | |
| License | |
| Language | |
| Last commit | |
| Release cadence | |
| Contributors | |

**Installation & First Run**

- [ ] Cloned / downloaded
- [ ] Read README fully
- [ ] Attempted install
- Time to first run: ___
- Install method: (pip / Docker / other)
- Minimum requirements: (RAM, CPU, disk, containers)
- Windows compatible? (native / Docker / WSL only / no)
- Did it work on first try? (yes / no — describe issues)

**Document Parsing**

| Capability | Supported? | Quality (1-5) | Notes |
|------------|-----------|----------------|-------|
| PDF text extraction | | | |
| PDF table extraction | | | |
| PDF figure/image extraction | | | |
| PDF formula/equation handling | | | |
| Scanned PDF (OCR) | | | |
| DOCX | | | |
| XLSX/CSV | | | |
| PPTX | | | |
| HTML | | | |
| Markdown | | | |
| Images (JPG/PNG) | | | |
| Other formats | | | |

Parser details:
- What parsing engine(s)? (PyMuPDF, docling, unstructured, custom, etc.)
- Can you select parser per document?
- Does it preserve layout/structure?

**Chunking**

| Capability | Supported? | Notes |
|------------|-----------|-------|
| Fixed-size chunking | | |
| Semantic chunking | | |
| Domain-specific templates | | |
| Parent-child chunks | | |
| User can edit/merge/split chunks | | |
| Custom chunking logic | | |

**Retrieval & Search**

| Capability | Supported? | Notes |
|------------|-----------|-------|
| Vector similarity search | | |
| BM25 / keyword search | | |
| Hybrid (vector + keyword) | | |
| Reranking | | |
| Knowledge Graph / GraphRAG | | |
| Cross-language search | | |
| Metadata filtering | | |
| Multi-document search | | |
| Collection/workspace isolation | | |

Vector store options: ___

**LLM Integration**

| Capability | Supported? | Notes |
|------------|-----------|-------|
| OpenAI | | |
| Anthropic (Claude) | | |
| Local models (Ollama/vLLM) | | |
| OpenRouter | | |
| Azure OpenAI | | |
| Other providers | | |
| Streaming responses | | |
| Custom system prompts | | |

**UI/UX**

| Feature | Supported? | Quality (1-5) | Notes |
|---------|-----------|----------------|-------|
| Chat interface | | | |
| Document upload | | | |
| Source citations | | | |
| PDF viewer with highlights | | | |
| Image/figure display | | | |
| Chunk visualization/editing | | | |
| Search/retrieval testing | | | |
| Dark mode | | | |
| Mobile responsive | | | |
| Embeddable widget | | | |

**Advanced Features**

| Feature | Supported? | Notes |
|---------|-----------|-------|
| Agent / workflow builder | | |
| Memory system | | |
| Web search fallback | | |
| Data connectors (Slack, etc.) | | |
| MCP support | | |
| API for integration | | |
| SSO / LDAP auth | | |
| Multi-user / teams | | |
| RBAC permissions | | |
| Evaluation / testing tools | | |
| Observability / logging | | |

**Architecture Notes**

- Tech stack: ___
- Database(s): ___
- Required services: ___
- Horizontal scaling: (yes / no / how)
- Plugin/extension system: (yes / no / how)

**Scores (1-5, relative to MEINRAG)**

| Dimension | Score | Justification |
|-----------|-------|---------------|
| Ease of setup | /5 | |
| Document parsing quality | /5 | |
| Retrieval quality | /5 | |
| UI/UX polish | /5 | |
| Extensibility / hackability | /5 | |
| Resource efficiency | /5 | |
| Feature breadth | /5 | |
| Community / maintenance | /5 | |
| Windows support | /5 | |
| Privacy / offline capability | /5 | |

**Key Takeaways**

- Best feature worth adopting: ___
- Biggest weakness: ___
- Would I switch from MEINRAG? (yes / no / partial — why)
- Ideas for MEINRAG improvement: ___

---

## Quick Research Checklist Per Project

Use this to stay efficient. Spend ~30-60 min per project.

```
[ ] 1. Read GitHub README (5 min)
[ ] 2. Check stars, license, last commit, contributor count (2 min)
[ ] 3. Browse documentation site (10 min)
[ ] 4. Try cloud demo if available (10 min)
[ ] 5. Watch a demo video if available on YouTube (5 min)
[ ] 6. Attempt local install (15 min, skip if Docker-only and no Docker)
[ ] 7. Upload a test PDF and ask a question (10 min)
[ ] 8. Fill in evaluation template (5 min)
```

**Test PDF**: Use `test cases/attention_is_all_you_need.pdf` — it has text, tables, figures, equations, and references. This gives a consistent baseline across all projects.

---

## Test Questions (use the same across all projects)

Ask these after uploading the Attention paper:

1. **Factual**: "What is the dimension of the model in the Transformer architecture?"
2. **Table**: "What are the BLEU scores reported for the base and big Transformer models?"
3. **Figure**: "Describe the Transformer architecture diagram"
4. **Formula**: "What is the attention function formula?"
5. **Cross-reference**: "Which papers are cited for positional encoding?"
6. **Synthesis**: "How does multi-head attention differ from single-head attention?"

For each question, note:
- Did it find the right chunks?
- Were citations/sources shown?
- Was the answer accurate?
- Response time?

---

## Cloud Demos (no install needed)

Try these first to save time:

| Project | Cloud Demo URL |
|---------|---------------|
| RAGFlow | https://cloud.ragflow.io |
| Dify | https://cloud.dify.ai |
| Open WebUI | (no public demo, Docker only) |
| AnythingLLM | (desktop app download) |
| Quivr | https://quivr.com |
| Onyx | (no public demo) |

---

## Final Report Template

After evaluating all projects, compile into this structure:

```markdown
# RAG Landscape Report — [Date]

## Executive Summary
- Total projects evaluated: ___
- Best overall: ___
- Best for our use case: ___
- Key findings: (3-5 bullet points)

## Ranking by Dimension

### Ease of Setup (1 = hardest, 5 = easiest)
| Rank | Project | Score | Notes |
|------|---------|-------|-------|
| 1 | | | |
| ... | | | |

### Document Parsing Quality
(same table format)

### Retrieval Quality
(same table format)

### UI/UX Polish
(same table format)

### Resource Efficiency
(same table format)

## Feature Comparison Matrix

| Feature | MEINRAG | RAGFlow | Dify | Open WebUI | ... |
|---------|---------|---------|------|------------|-----|
| PDF tables | Y | Y | | | |
| PDF figures | Y | Y | | | |
| Formula OCR | Y | N | | | |
| GraphRAG | N | Y | | | |
| ... | | | | | |

## Features Worth Adopting

| Feature | From | Effort | Impact | Priority |
|---------|------|--------|--------|----------|
| | | | | |

## Conclusion
- MEINRAG's unique position: ___
- Recommended roadmap: ___
- Projects to keep watching: ___
```

---

## Notes Space

Use this area for general observations during research:

```
[Your notes here]
```
