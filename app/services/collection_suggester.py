from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel

SUGGESTION_PROMPT = """\
Analyze the following document excerpt and suggest a SHORT collection name (1-2 words, lowercase, hyphen-separated if needed).

Choose a category that describes the document type or domain:
- Examples: "legal", "medical", "technical", "financial", "hr", "marketing", "research"
- Be specific but concise
- Return ONLY the collection name, nothing else

Document excerpt:
{content}

Collection name:"""


def suggest_collection(chunks: list[Document], llm: BaseChatModel) -> str:
    """Analyze document content and suggest a collection name."""
    # Take first 3 chunks or ~1500 chars
    content = "\n\n".join([c.page_content for c in chunks[:3]])
    content = content[:1500]

    response = llm.invoke(SUGGESTION_PROMPT.format(content=content))
    suggestion = response.content.strip().lower()

    # Clean: remove quotes, periods, ensure valid format
    suggestion = suggestion.replace('"', '').replace("'", '').replace('.', '')
    suggestion = suggestion.replace(' ', '-')

    return suggestion[:50]  # Max 50 chars
