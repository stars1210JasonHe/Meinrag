"""北大法宝 / export noise cleaner for legal-corpus ingest.

Rules iteratively validated against a full real-corpus backup (~940 docs). All
rules are line/char-bounded — they never strip to EOF and tolerate the Kangxi 大
(⼤) variant. Applied per-chunk after parse when settings.text_clean_enabled is
true (legal deployment).
"""
import re


def clean(t: str) -> str:
    # 1. internal NAS path leak link → remove entirely (its link-text IS the leak)
    t = re.sub(r'\[\\+100\.85\.155\.22\\email\\index\]\(file:///[^)]*\)', '', t)
    # 1b. whole-line 北大法宝 navigation links (法宝联想 related-docs + metadata badges +
    #     更多/快讯/原文链接) — a line that IS a markdown link to pkulaw or javascript:.
    #     Drop the whole line (title included), else pattern 2 keeps the related-doc TITLE
    #     as retrieval-polluting text. Fully line-bounded (no \n in any class, (?m)$ ends
    #     the line) so it can NEVER gobble real law text on following lines.
    t = re.sub(r'(?m)^[ \t]*\[[^\]\n]+\]\((?:https?://[^\s)\n]*pkulaw\.[^\n]*|javascript:[^\n]*)$', '', t)
    # 2. markdown links (http/js/file) → keep visible text, drop the target
    t = re.sub(r'\[([^\]]*?)\]\((?:javascript:|https?://|file:///)[^)]*\)', r'\1', t)
    # 3. 北大法宝 citation codes (tolerate spaces in 【 】 + markdown [CLI..](/fbm) form)
    t = re.sub(r'【\s*法宝引证码\s*】\s*\[?CLI[\.\d]*\]?(?:\(/fbm\))?', '', t)
    # 4. docling image placeholders
    t = re.sub(r'<!--\s*image\s*-->', '', t)
    # 5. 北大法宝 copyright/source footers — several forms, all anchored on a unique 北大法宝
    #    promo phrase + bounded window (never to EOF). Tolerate the Kangxi 大 variant (⼤).
    t = re.sub(r'专业提供法律信息、法学知识和法律软件领域各类[\s\S]{0,220}', '', t)           # main promo footer (anchor to '…各类'; chunk cuts truncate the trailing '解决方案')
    t = re.sub(r'(?:北[大⼤])?法宝为您提供丰富的参考资料[，,][\s\S]{0,40}?核对[。\.]?', '', t)  # 'reference material' footer sentence (北大 may split off at chunk boundary)
    t = re.sub(r'(?m)^.*chinalawinfo\.com.*$', '', t)                                   # '文件提供：…chinalawinfo.com 北大法宝 Tel:…' source line (vip./law. subdomains)
    t = re.sub(r'(?m)^.*法宝快讯[：:].*$', '', t)                                         # '法宝快讯： …？ 法宝 V6 …？' promo line
    t = re.sub(r'【\s*北[大⼤]法宝\s*】\s*pkulaw\.[a-z]{0,3}', '', t)                      # '【北大法宝】pkulaw.cn' header badge
    t = re.sub(r'©?\s*北[大⼤]法宝[：:]\s*[\(（]?\s*', '', t)
    t = re.sub(r'(?m)^[\s　]*(?:北[大⼤])?法宝[\s　]*$', '', t)                            # standalone 北大法宝 / 法宝 fragment line
    t = re.sub(r'www\.pkulaw\.c[a-z]{1,3}[）)\s]*', '', t)
    # 6. 北大法宝 interactive blocks: 法宝联想(...) + related-content count lines + 智能发现 + ;)
    t = re.sub(r'[（(]\s*法宝联想[：:][\s\S]{0,260}?[）)]', '', t)
    t = re.sub(r'(?m)^\s*法宝联想[：:].*$', '', t)                          # 法宝联想: line — bare OR inline-counts (法宝联想：地方法规 1 篇司法案例 174 篇…)
    t = re.sub(r'\*\*\s*法宝(?:联想|律师)\s*\*\*', '', t)                    # bold-markdown 法宝联想/法宝律师 (docx→md, no colon). 法宝提示 KEPT (carries 失效+successor signal)
    t = re.sub(r'(?m)^\s*(?:司法案例|行政案例|裁判文书|关联法规|实务指南|期刊|律所实务|法学期刊|'
               r'法学文献|实务专题|部门规章|司法解释|其他规范性文件|地方法规规章|案例与裁判文书|'
               r'专题参考|案例报道|仲裁案例|中央法规|地方法规|行政法规|裁判规则)'
               r'\s*约?\s*\d+\s*篇.*$', '', t)
    t = re.sub(r'[ \t]*;\)', '', t)
    t = re.sub(r'智能发现', '', t)
    # 6c. cruft types found by an independent A/B probe (no 法宝/pkulaw token, so the earlier rules missed them):
    #     concatenated 法宝联想 count-runs (inline variant of the line form above)
    #     structural (not category-list — whack-a-mole): ≥2 consecutive 'CN-term(2-10) 约? N 篇'.
    #     Safe: legit law rarely has 2+ consecutive 'CN N 篇'; a single count + law text won't match
    #     (needs 2 items), and '第 N 篇' book markers have only 1 CN char before the digit → excluded.
    t = re.sub(r'(?:[一-鿿]{2,10}\s*约?\s*\d+\s*篇[\s、，]*){2,}', '', t)
    #     lone single count-line (e.g. '法律动态 1 篇' interspersed between law articles) —
    #     whole line is entirely count-item(s); law-article lines have more content so won't match
    t = re.sub(r'(?m)^\s*(?:[一-鿿]{2,10}\s*约?\s*\d+\s*篇[\s、，]*)+\s*$', '', t)
    #     leading/bare orphan count: a 3+digit number + 篇 left when the category-run was stripped
    #     (e.g. '…11796 篇第六十九条'). 3+ digits = a case-count (100+), never a law structural 篇.
    t = re.sub(r'\d{3,}\s*篇', '', t)
    #     北大法宝 知识脉络 breadcrumb tree (whole CN-only line, ≥3 '>' segments; outranked law @rank-1)
    t = re.sub(r'(?m)^\s*[一-鿿]{2,8}(?:\s*>\s*[一-鿿、，()（）]{1,18}){2,}\s*$', '', t)
    #     '下载日期：2022/12/21' export stamp + bare '1/9' PDF page-number lines (whole-line)
    t = re.sub(r'下载日期[：:]\s*\d{4}\s*/\s*\d{1,2}\s*/\s*\d{1,2}', '', t)
    t = re.sub(r'(?m)^\s*\d{1,4}\s*/\s*\d{1,4}\s*$', '', t)
    # 6b. stray editing/input-method junk found mixed into legal text (real-corpus instrumentation)
    t = re.sub(r'好饿但是不想动', '', t)
    t = re.sub(r'法小宝', '', t)
    # 7. any leftover bare pkulaw/file/js URLs + internal-path catch-all
    t = re.sub(r'\(?(?:https?://(?:www\.)?pkulaw\.(?:com|cn)|file:///|javascript:SLC)[^\s)]*\)?', '', t)
    t = re.sub(r'(?:[a-z]{0,3}\.)?pkulaw\.(?:com|cn)(?:[/?][^\s)\]<]*)?', '', t)          # bare pkulaw URLs/fragments (no scheme: 'w.pkulaw.com/…')
    t = re.sub(r'手机扫一扫关注北[大⼤]法宝公众号', '', t)                                    # QR-code footer line
    t = re.sub(r'法宝\s*V6\s*有何新特色[？?]?', '', t)                                       # '法宝 V6 有何新特色？' promo fragment
    t = re.sub(r'\\*100\.85\.155\.22[\\/][^\s)\]]*', '', t)
    # 8. cleanup whitespace/blank lines created by removals
    t = re.sub(r'[ \t]{2,}', ' ', t)
    t = re.sub(r'(?m)^[ \t]+$', '', t)
    t = re.sub(r'\n{3,}', '\n\n', t)
    return t.strip()
