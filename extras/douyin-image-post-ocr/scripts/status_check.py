# -*- coding: utf-8 -*-
"""全量状态核查：知识库 / 账本 / 采集清单三方对照，一次看清缺口在哪。

用法：
    python status_check.py
读出：知识库条数与结构、账本条数、采集清单类型分布、各类已入库/未入库缺口。
"""
from __future__ import annotations

import collections
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import KB, LEDGER, WORK  # noqa: E402

META = WORK / "meta_images.json"


def main() -> None:
    files = sorted(KB.glob("collection-*.md"))
    kb_ids = {f.stem.replace("collection-", "") for f in files}
    ocr = art = 0
    for f in files:
        t = f.read_text(encoding="utf-8", errors="ignore")
        if "## 图片文字 (OCR)" in t:
            ocr += 1
        if "## 文章正文" in t:
            art += 1
    print("=== 知识库 ===")
    print(f"  笔记文件 {len(files)}  含 OCR 段 {ocr}  含文章正文 {art}")

    if not META.exists():
        print(f"\n（未找到采集清单 {META}，跳过覆盖分析。先跑 collect_images.py）")
        return
    meta = json.loads(META.read_text(encoding="utf-8"))

    posts = [x for x in meta if x.get("aweme_type") != 163 and (x.get("image_count") or 0) > 0]
    articles = [x for x in meta if x.get("aweme_type") == 163]
    videos = [x for x in meta if x.get("aweme_type") != 163 and not (x.get("image_count") or 0)]

    print(f"\n=== 采集清单 {len(meta)} 条 ===")
    print("  类型分布:", dict(collections.Counter(f"aweme_type={x.get('aweme_type')}" for x in meta)))

    print(f"\n{'类别':10s} {'总数':>6s} {'已入库':>7s} {'未入库':>7s}")
    print("-" * 36)
    for name, lst in [("图文帖", posts), ("长文", articles), ("普通视频", videos)]:
        got = sum(1 for x in lst if str(x.get("aweme_id")) in kb_ids)
        print(f"{name:10s} {len(lst):>6d} {got:>7d} {len(lst)-got:>7d}")

    if LEDGER.exists():
        con = sqlite3.connect(str(LEDGER))
        cur = con.cursor()
        cur.execute("select count(*) from promotions")
        n = cur.fetchone()[0]
        cur.execute("select aweme_id from promotions")
        # 账本里的 aweme_id 形如 "collection:<id>"，需剥前缀后与笔记文件名比对
        led = {str(r[0]).split(":", 1)[-1] for r in cur.fetchall()}
        con.close()
        print(f"\n=== 账本 promotions {n} 条 ===")
        print(f"  账本 ∩ 笔记文件 {len(led & kb_ids)} | 账本独有 {len(led - kb_ids)} | 笔记独有 {len(kb_ids - led)}")


if __name__ == "__main__":
    main()
