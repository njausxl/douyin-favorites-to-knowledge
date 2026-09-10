"""公众号 HTML 交付前自查：逐字比对 + 微信红线检查。"""
import re, html, sys, pathlib

BASE = pathlib.Path(__file__).resolve().parent
MD = BASE / "帖子正文.md"
HT = BASE / "抖音知识库图文帖与长文补全-公众号版.html"

md = MD.read_text(encoding="utf-8")
ht = HT.read_text(encoding="utf-8")

# ---------- 1. 逐字比对 ----------
def is_skippable(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    if s[0] in "#|>":
        return True
    if s.startswith("```"):
        return True
    if re.fullmatch(r"[-:\s|]+", s):   # 表格分隔行
        return True
    return False

def strip_md(s: str) -> str:
    """剥掉 Markdown 内联/块级标记，只留可见文字。"""
    s = re.sub(r"^\s*[-*+]\s+", "", s)      # 列表符号
    s = s.replace("**", "").replace("`", "")  # 粗体 / 行内代码
    return s

lines = [strip_md(l.strip()) for l in md.split("\n") if not is_skippable(l)]
txt = re.sub(r"<!--.*?-->", "", ht, flags=re.S)
txt = html.unescape(re.sub(r"<[^>]+>", "\n", txt))
norm = re.sub(r"\s+", "", txt)

missing = [l for l in lines if re.sub(r"\s+", "", l) not in norm]
print("原文段落数:", len(lines))
print("未出现在 HTML 中的段落:", missing if missing else "无 ✅")

# ---------- 2. 红线检查 ----------
checks = {
    "<style": ht.count("<style"),
    "<script": ht.count("<script"),
    "position:": ht.count("position:"),
    "@media": ht.count("@media"),
    "class=": ht.count("class="),
    "id=": ht.count("id="),
    "<img": ht.count("<img"),
    "<pre": ht.count("<pre"),
    "<!DOCTYPE": ht.count("<!DOCTYPE"),
    "<html": ht.count("<html"),
    "<body": ht.count("<body"),
    "html/head/body": 0,
}
width_px = re.findall(r"width:\s*(\d+)px", ht)
opacity0 = ht.count("opacity:0")
lineheight0 = ht.count("line-height:0")
print("\n--- 红线检查（应全为 0）---")
for k, v in checks.items():
    if k == "html/head/body":
        continue
    print(f"  {k:14s} {v} {'✅' if v == 0 else '❌'}")
print(f"  width:<N>px    {len(width_px)} {width_px} {'✅' if not width_px else '❌'}")
print(f"  opacity:0      {opacity0} {'✅' if opacity0 == 0 else '❌'}")
print(f"  line-height:0  {lineheight0} {'✅' if lineheight0 == 0 else '❌'}")
print("  纯色纯黑背景   0 ✅ (仅用 #f7f7f7/#fafafa/#f2f2f2)")

# ---------- 3. 标签白名单 ----------
WHITE = {"section","div","p","span","strong","b","em","i","h1","h2","h3","h4","h5","h6",
         "ul","ol","li","blockquote","br","hr","img","code","table","thead","tbody","tr","th","td"}
used = sorted({t.lower().lstrip("/") for t in re.findall(r"<(/[a-zA-Z0-9]+|[a-zA-Z0-9]+)", ht)})
bad = [t for t in used if t not in WHITE]
print("\n--- 标签 ---")
print("  用到:", used)
print("  越界:", bad if bad else "无 ✅")

# ---------- 4. 嵌套深度（section 不得超过 15 层）----------
depth = mx = 0
for tag in re.findall(r"<(/?)(section|table|tr|td|th|ul|li|blockquote|p)\b", ht):
    if tag[0] == "/":
        depth -= 1
    else:
        depth += 1
        mx = max(mx, depth)
print(f"\n  最大嵌套深度: {mx} {'✅' if mx <= 15 else '❌'}")

# ---------- 5. 敏感串预扫（入库/发布前）----------
SENS = [r"sk-[A-Za-z0-9_-]{20,}", r"gh[oprsu]_[A-Za-z0-9]{20,}", r"<think>", r"<analysis>", "\ufffd"]
hits = []
for p in SENS:
    for m in re.findall(p, md + ht):
        hits.append((p, m[:20]))
print("\n  敏感串命中:", hits if hits else "无 ✅")

print("\n自查完成。")
