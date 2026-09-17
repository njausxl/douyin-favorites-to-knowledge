# -*- coding: utf-8 -*-
"""误筛审计：用文本模型逐条判定「未入库的普通视频」是否属于知识类，找出被筛选口径误伤的内容。

**为什么需要它**：抖音收藏的筛选阶段常用「游戏/娱乐关键词」排除法，
但关键词只看标题，遇到标签堆砌、描述不完整的条目就会漏判 ——
健身、心理、历史、哲学、理财这类内容被成批误伤是常见结果。

用法：
    export SILICONFLOW_API_KEY=...
    python audit_videos.py --limit 20      # 小批量试验（验证模型输出格式）
    python audit_videos.py                 # 全量（可断点续跑）
产出：
    $WORK/video_audit.jsonl                # 逐条判定（断点续跑依据）
    $WORK/video_audit_keep.json            # 判定为知识类的清单
环境变量：AUDIT_MODEL（默认 Qwen/Qwen2.5-7B-Instruct）
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import KB, WORK  # noqa: E402

META = WORK / "meta_images.json"
OUTL = WORK / "video_audit.jsonl"
KEEP = WORK / "video_audit_keep.json"

KEY = os.environ.get("SILICONFLOW_API_KEY", "")
MODEL = os.environ.get("AUDIT_MODEL", "Qwen/Qwen2.5-7B-Instruct")
API = "https://api.siliconflow.cn/v1/chat/completions"
BATCH = 35

SYS = """你是内容分类助手。用户有一个「个人知识库」（Obsidian），用来沉淀可复用的知识。

收录（keep=true）：AI/工具/技能/科研/编程；自我提升/心理/认知；读书/社科/人文/历史；
学习方法/教育/备考；健康/运动/医学常识/科普；职场/理财/商业/创业方法论。

不收录（keep=false）：游戏攻略（改枪、跑刀、画质设置、物资点等）；
数码硬件选购（装机、显卡、开箱）；生活/美食/探店/旅游/本地生活；
购物/带货/消费推荐；娱乐/音乐/舞蹈/搞笑/情感八卦/影视；纯风景、纯记录、无信息量的感慨。

判断以描述文本为准；描述为空或纯标签、无法判断时 keep=false，reason 写「信息不足」。

只输出一个 JSON 数组，不要 markdown 代码块，不要任何解释。
每个元素：{"id":"<原样>","topic":"<主题，≤8字>","keep":true或false,"reason":"<理由，≤14字>"}"""


def call(items):
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYS},
            {"role": "user", "content": json.dumps(items, ensure_ascii=False)},
        ],
        "temperature": 0.1,
        "max_tokens": 4000,
    }
    req = urllib.request.Request(
        API,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"]


def parse(txt: str):
    t = re.sub(r"^```(?:json)?|```$", "", txt.strip(), flags=re.M).strip()
    m = re.search(r"\[.*\]", t, flags=re.S)
    if not m:
        raise ValueError("no JSON array in response: " + t[:200])
    return json.loads(m.group(0))


def main() -> None:
    if not KEY:
        raise SystemExit("请先设置 SILICONFLOW_API_KEY")
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    kb_ids = {f.stem.replace("collection-", "") for f in KB.glob("collection-*.md")}
    meta = json.loads(META.read_text(encoding="utf-8"))
    # 普通视频 = 非长文、无图列表、且未入库
    vids = [x for x in meta
            if x.get("aweme_type") != 163
            and not (x.get("image_count") or 0)
            and str(x.get("aweme_id")) not in kb_ids]
    print(f"未入库普通视频: {len(vids)} 条")

    done = {}
    if OUTL.exists():
        for line in OUTL.open(encoding="utf-8"):
            try:
                r = json.loads(line)
                done[str(r["id"])] = r
            except Exception:
                pass
    print(f"已有结果: {len(done)} 条（续跑）")

    todo = [v for v in vids if str(v["aweme_id"]) not in done]
    if limit:
        todo = todo[:limit]
    print(f"本次待处理: {len(todo)} 条，模型 {MODEL}")

    batches = (len(todo) + BATCH - 1) // BATCH
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        items = [{"id": str(v["aweme_id"]), "author": (v.get("author") or "")[:16],
                  "desc": (v.get("description") or "").replace("\n", " ")[:150]} for v in chunk]
        for attempt in range(3):
            try:
                res = parse(call(items))
                break
            except Exception as e:
                print(f"  批次 {i//BATCH+1} 第 {attempt+1} 次失败: {str(e)[:120]}")
                time.sleep(3)
        else:
            print(f"  批次 {i//BATCH+1} 放弃")
            continue
        with OUTL.open("a", encoding="utf-8") as f:
            for r in res:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                done[str(r.get("id"))] = r
        print(f"  批次 {i//BATCH+1}/{batches} 完成：{len(res)} 条，keep={sum(1 for r in res if r.get('keep'))}")

    keep = []
    for v in vids:
        r = done.get(str(v["aweme_id"]))
        if r and r.get("keep"):
            keep.append({**v, "topic": r.get("topic", ""), "reason": r.get("reason", "")})
    KEEP.write_text(json.dumps(keep, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n=== 已判定 {len(done)} 条，建议入库 {len(keep)} 条 ===")
    for k, n in collections.Counter(r["topic"] for r in keep).most_common(30):
        print(f"  {k}: {n}")
    total_min = sum((r.get("duration_seconds") or 0) for r in keep) / 60
    print(f"候选音视频总时长约 {total_min:.0f} 分钟（{total_min/60:.1f} 小时）")
    print(f"→ 清单已写 {KEEP}")


if __name__ == "__main__":
    main()
