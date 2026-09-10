# -*- coding: utf-8 -*-
"""根据 staged.jsonl 与知识库现状, 生成「疑似误筛图文帖补录报告」。"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from _paths import KB, ROOT, WORK  # noqa: E402

OUT = ROOT / "docs" / "疑似误筛补录报告.md"

sys.path.insert(0, str(WORK))
import backfill_misfiltered as bf  # noqa: E402


def main() -> None:
    staged = [json.loads(l) for l in (ROOT / "ocr_test/backfill/staged.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    by_id = {it["aweme_id"]: it for it in staged}
    cat_of = {aid: g for g, ids in bf.PLAN.items() for aid in ids}

    have = {f[11:-3] for f in os.listdir(KB) if f.startswith("collection-") and f.endswith(".md")}

    rows = []
    for aid in bf.INCLUDE:
        it = by_id.get(aid)
        ocr = (it or {}).get("ocr") or {}
        txt = (ocr.get("text") or "").strip()
        body = re.sub(r"^### 图 .*$", "", txt, flags=re.M).strip()
        note = KB / f"collection-{aid}.md"
        note_txt = note.read_text(encoding="utf-8") if note.exists() else ""
        rows.append({
            "aid": aid,
            "cat": cat_of.get(aid, "?"),
            "author": (it or {}).get("author", ""),
            "title": ((it or {}).get("title") or "")[:40],
            "images": ocr.get("image_count", 0),
            "images_ok": ocr.get("images_ok", 0),
            "words": len(body),
            "promoted": aid in have,
            "has_ocr_section": "## 图片文字 (OCR)" in note_txt,
        })

    total_img = sum(r["images"] for r in rows)
    total_words = sum(r["words"] for r in rows)
    promoted = [r for r in rows if r["promoted"]]
    with_ocr = [r for r in rows if r["has_ocr_section"]]

    L: list[str] = []
    L.append("# 疑似误筛图文帖 · 补录报告")
    L.append("")
    L.append("生成时间: 2026-09-10")
    L.append("")
    L.append("## 总览")
    L.append("")
    L.append("| 指标 | 数值 |")
    L.append("|---|---|")
    L.append(f"| 从未选中的图文帖 | 81 条 |")
    L.append(f"| 判定为「疑似误筛」并补录 | **{len(bf.INCLUDE)} 条** |")
    L.append(f"| 成功写入知识库 | **{len(promoted)} 条** |")
    L.append(f"| 带 OCR 段 | **{len(with_ocr)} 条** |")
    L.append(f"| 处理图片 | **{total_img} 张**（识别出文字 {sum(r['images_ok'] for r in rows)} 张）|")
    L.append(f"| 提取文字 | **{total_words:,} 字** |")
    L.append(f"| 明确排除 | {sum(len(v) for v in bf.EXCLUDED.values())} 条 |")
    L.append("")
    L.append("## 分类明细")
    L.append("")
    for cat, ids in bf.PLAN.items():
        sub = [r for r in rows if r["cat"] == cat]
        L.append(f"### {cat}（{len(sub)} 条 / {sum(r['images'] for r in sub)} 图 / {sum(r['words'] for r in sub):,} 字）")
        L.append("")
        L.append("| aweme_id | 作者 | 图 | 识别 | 字数 | 入库 |")
        L.append("|---|---|---|---|---|---|")
        for r in sorted(sub, key=lambda x: -x["words"]):
            L.append(f"| {r['aid']} | {r['author'][:12]} | {r['images']} | {r['images_ok']} | {r['words']:,} | {'✅' if r['promoted'] else '❌'} |")
        L.append("")
    L.append("## 明确排除的条目")
    L.append("")
    for cat, ids in bf.EXCLUDED.items():
        L.append(f"- **{cat}**（{len(ids)} 条）: {', '.join(ids)}")
    L.append("")
    L.append("## 说明")
    L.append("")
    L.append("- 补录走的是集成后的主同步管线：`_apply_configured_stages`（自动 OCR）→ `build_review` → `build_approval` → `promote`。")
    L.append("- OCR 模型: `Qwen/Qwen3-VL-30B-A3B-Instruct`。")
    L.append("- 笔记路径: `知识库/collection-{aweme_id}.md`，正文见「## 图片文字 (OCR)」段。")
    L.append("- 「排除」仅代表按「游戏 / 数码硬件 / 本地生活消费 / 纯娱乐」口径不补；如需扩大范围可随时告知。")
    L.append("")

    OUT.write_text("\n".join(L), encoding="utf-8")
    print("已写入", OUT)
    print("补录 %d 条, 已入库 %d, 带OCR %d, 图片 %d, 字数 %d" % (len(bf.INCLUDE), len(promoted), len(with_ocr), total_img, total_words))
    missing = [r["aid"] for r in rows if not r["promoted"]]
    if missing:
        print("未入库:", missing)


if __name__ == "__main__":
    main()
