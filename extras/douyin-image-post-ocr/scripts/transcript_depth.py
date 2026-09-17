# -*- coding: utf-8 -*-
"""转录深度审计：比对「正文长度」与「视频时长」，找出疑似被截断的长视频。

**为什么需要它**：SenseVoice 的输出里常带 `🎼` 标记（音频事件 / 音乐段），
**它不代表整篇是噪声**。一看到 `🎼` 就判"转录失败"会大面积误报。

正确的判据是**信息密度**（正文去梗后字数 ÷ 视频秒数）：
- 正常口播约 3–6 字/秒；
- 明显偏低（< 1.0 字/秒）才说明音频被截断、下载失败或 ASR 空转。

用法：
    python transcript_depth.py            # 打印审计结果
产出：
    $WORK/transcript_depth.json           # 逐条明细
"""
from __future__ import annotations

import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import KB, WORK  # noqa: E402

META = WORK / "meta_images.json"
OUT = WORK / "transcript_depth.json"
LOW_RATE = 1.0          # 字/秒，低于此值判为疑似截断
LONG_SECONDS = 600      # 只审计 ≥10 分钟的视频


def section(text: str, header: str) -> str:
    m = re.search(rf"{re.escape(header)}\s*\n(.*?)(?=\n## |\n### |\Z)", text, re.S)
    return m.group(1).strip() if m else ""


def main() -> None:
    meta = {}
    if META.exists():
        meta = {str(x["aweme_id"]): x for x in json.loads(META.read_text(encoding="utf-8"))}

    rows = []
    for f in sorted(KB.glob("collection-*.md")):
        t = f.read_text(encoding="utf-8", errors="ignore")
        aid = f.stem.replace("collection-", "")
        tr = section(t, "### 转录").replace("🎼", "")
        ocr = section(t, "## 图片文字 (OCR)")
        art = section(t, "## 文章正文")
        m = meta.get(aid, {})
        dur = m.get("duration_seconds") or 0
        body = len(ocr) if ocr else (len(art) if art else len(tr))
        rows.append({
            "id": aid, "dur": dur, "dur_min": round(dur / 60, 1),
            "body": body, "tr_len": len(tr), "ocr_len": len(ocr), "art_len": len(art),
            "rate": round(body / dur, 2) if dur else None,
            "desc": (m.get("description") or "")[:40],
        })

    print(f"=== 知识库 {len(rows)} 条 ===")

    longs = [r for r in rows if r["dur"] >= LONG_SECONDS]
    rates = [r["rate"] for r in longs if r["rate"]]
    if rates:
        print(f"长视频（≥{LONG_SECONDS//60} 分钟）{len(longs)} 条，"
              f"密度中位数 {statistics.median(rates):.2f} 字/秒，均值 {statistics.mean(rates):.2f}")

    suspect = sorted([r for r in longs if (r["rate"] or 0) < LOW_RATE], key=lambda x: x["rate"] or 0)
    print(f"\n--- 疑似截断（密度 < {LOW_RATE} 字/秒）：{len(suspect)} 条 ---")
    for r in suspect:
        print(f'  {r["id"]}  {r["dur_min"]:>7.1f}分  正文{r["body"]:>6}字  密度={r["rate"]}  {r["desc"]}')

    nobody = [r for r in rows if r["body"] == 0]
    print(f"\n--- 完全无正文：{len(nobody)} 条 ---")
    for r in nobody:
        print(f'  {r["id"]}  {r["dur_min"]}分  {r["desc"]}')

    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n→ 明细已写 {OUT}")


if __name__ == "__main__":
    main()
