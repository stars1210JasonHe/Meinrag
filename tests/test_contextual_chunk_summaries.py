"""Contextual chunk summaries: the document opening rides in front of every chunk so the
summary can name the document and the article/section the chunk belongs to.

Guards: prompt selection (contextual vs plain, script-dependent wording), the head builder
(order, minimum length, cap, file name), and that the head actually reaches the LLM call.
"""
import pytest
from langchain_core.documents import Document

from app.services import summary_generator as sg


class _Settings:
    summary_provider = "openai"
    openrouter_api_key = None
    summary_model = "gpt-4o-mini"
    summary_min_chars = 20
    summary_contextual = True
    summary_context_head_chars = 1200


class _CapturingLLM:
    """Records the messages it was asked to answer."""

    def __init__(self):
        self.calls = []

    async def ainvoke(self, messages):
        self.calls.append(messages)

        class R:
            content = "a summary"
        return R()


def _chunk(idx, text, source="law.docx"):
    return Document(page_content=text, metadata={"chunk_index": idx, "source_file": source, "chunk_type": "text"})


# ---- prompt selection

def test_plain_prompt_when_contextual_is_off():
    s = _Settings(); s.summary_contextual = False
    assert sg.chunk_summary_prompt("第三十二条 用人单位" * 5, s, "some head") == sg.CHUNK_SUMMARY_PROMPT


def test_plain_prompt_when_no_head_is_available():
    assert sg.chunk_summary_prompt("some english text", _Settings(), None) == sg.CHUNK_SUMMARY_PROMPT


def test_contextual_prompt_picks_wording_by_script():
    zh = sg.chunk_summary_prompt("第三十二条用人单位与其招用的人员发生用工争议", _Settings(), "HEAD-ZH")
    en = sg.chunk_summary_prompt("The employer shall pay severance within thirty days.", _Settings(), "HEAD-EN")
    assert "HEAD-ZH" in zh and "文件开头" in zh
    assert "HEAD-EN" in en and "Document opening" in en
    assert zh != en


# ---- head builder

def test_head_is_ordered_by_chunk_index_and_starts_with_the_file_name():
    chunks = [_chunk(2, "third " * 40), _chunk(0, "first " * 40), _chunk(1, "second " * 40)]
    head = sg.build_doc_head(chunks, max_chars=5000)
    assert head.startswith("law.docx\n")
    assert head.index("first") < head.index("second")
    assert "third" not in head  # 240 + 280 chars already pass the 300-char stop


def test_head_stops_once_300_chars_are_collected_and_is_capped():
    chunks = [_chunk(i, ("x%d " % i) * 60) for i in range(10)]  # each chunk ~180 chars
    head = sg.build_doc_head(chunks, max_chars=5000)
    assert "x0" in head and "x1" in head          # two chunks reach 300 chars
    assert "x3" not in head                        # later chunks are not needed
    assert len(sg.build_doc_head(chunks, max_chars=100)) == 100


def test_head_without_file_name_is_just_the_text():
    chunks = [Document(page_content="body " * 80, metadata={"chunk_index": 0})]
    assert sg.build_doc_head(chunks, max_chars=5000).startswith("body ")


# ---- the head reaches the model

@pytest.mark.asyncio
async def test_generate_chunk_summary_sends_the_head_in_the_system_message():
    llm = _CapturingLLM()
    out = await sg.generate_chunk_summary("The employer shall pay severance within thirty days.", _Settings(), llm=llm,
                                          doc_head="ACT NO. 12 OF 2026\nAn Act about severance")
    assert out == "a summary"
    system_msg = llm.calls[0][0]
    assert "ACT NO. 12 OF 2026" in system_msg.content
    assert "Document opening" in system_msg.content


@pytest.mark.asyncio
async def test_generate_chunk_summary_without_head_uses_the_plain_prompt():
    llm = _CapturingLLM()
    await sg.generate_chunk_summary("The employer shall pay severance within thirty days.", _Settings(), llm=llm)
    assert llm.calls[0][0].content == sg.CHUNK_SUMMARY_PROMPT


@pytest.mark.asyncio
async def test_short_chunks_are_still_skipped():
    llm = _CapturingLLM()
    s = _Settings(); s.summary_min_chars = 200
    assert await sg.generate_chunk_summary("too short", s, llm=llm, doc_head="head") is None
    assert llm.calls == []
