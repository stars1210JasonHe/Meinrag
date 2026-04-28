"""Print the metadata of the first 3 chunks of one doc."""
import asyncio, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main():
    from app.config import get_settings
    from app.vectorstore.factory import create_vector_store_manager
    from app.llm.provider import create_embeddings
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from app.db.repositories import DocumentRepository

    settings = get_settings()
    vs = create_vector_store_manager(settings)
    vs.initialize(create_embeddings(settings))

    engine = create_async_engine(settings.database_url)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        docs = await DocumentRepository(s).list_all()
    if not docs:
        print("no docs"); return
    doc_id = docs[0]["doc_id"]
    chunks = vs.get_chunks_by_doc(doc_id)
    print(f"doc: {doc_id}  {docs[0].get('filename')}")
    print(f"chunk count: {len(chunks)}")
    print()
    # Group by chunk_type and find a text chunk
    text_chunks = [c for c in chunks if (c.metadata or {}).get('chunk_type') == 'text']
    print(f"text chunks: {len(text_chunks)}, table: {sum(1 for c in chunks if (c.metadata or {}).get('chunk_type') == 'table')}, image: {sum(1 for c in chunks if (c.metadata or {}).get('chunk_type') == 'image')}, formula: {sum(1 for c in chunks if (c.metadata or {}).get('chunk_type') == 'formula')}")
    print()
    sample = text_chunks[:3] if text_chunks else chunks[:3]
    for i, c in enumerate(sample):
        print(f"--- chunk {i} ---")
        meta = c.metadata or {}
        print(f"keys: {sorted(meta.keys())}")
        for k in ["chunk_index", "page", "chunk_type", "section_type", "label",
                  "headings", "summary"]:
            v = meta.get(k)
            if isinstance(v, str) and len(v) > 80:
                v = v[:77] + "..."
            print(f"  {k}: {v!r}")
        print(f"  content (first 100 chars): {c.page_content[:100]!r}")
        print()


asyncio.run(main())
