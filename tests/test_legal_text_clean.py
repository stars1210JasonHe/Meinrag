"""Tests for the 北大法宝 export-noise cleaner (app/services/legal_text_clean.py)."""
from app.services.legal_text_clean import clean


def test_inline_nonpkulaw_link_keeps_text():
    # a mid-line markdown link → keep visible text, drop the target (rule 2)
    assert clean("见 [某规定](https://example.com/x) 第三条") == "见 某规定 第三条"


def test_whole_line_pkulaw_nav_link_dropped():
    # a line that IS a pkulaw markdown link = nav/related-doc → dropped whole,
    # title included (rule 1b — else the related-doc title pollutes retrieval)
    out = clean("第一条 正文\n[相关法规链接](https://www.pkulaw.cn/x)\n第二条 正文")
    assert "相关法规链接" not in out and "第一条 正文" in out and "第二条 正文" in out


def test_strips_citation_code():
    assert "法宝引证码" not in clean("正文【法宝引证码】CLI.3.281033")


def test_strips_count_line():
    assert clean("第一条 正文\n司法案例 174 篇\n第二条 正文").count("174") == 0


def test_strips_breadcrumb_tree():
    out = clean("民法商法 > 民法 > 合同 > 买卖合同\n第一条 正文")
    assert "买卖合同" not in out and "第一条 正文" in out


def test_keeps_real_law_text_untouched():
    law = "第二百七十八条 下列事项由业主共同决定：\n（一）制定和修改管理规约"
    assert clean(law) == law


def test_never_strips_to_eof_on_footer():
    out = clean("正文一\n北大法宝：（\n第九条 真实法条内容保留")
    assert "第九条 真实法条内容保留" in out
