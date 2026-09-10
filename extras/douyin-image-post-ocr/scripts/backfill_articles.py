# -*- coding: utf-8 -*-
"""把抖音「长文(文章)」的正文补进知识库。

两类目标:
  A. 已入库的 24 条: 合并式回填 —— 在笔记里插入「## 文章正文」, 并把背景音乐幻觉出的
     噪声转录替换为说明行 (可 --keep-noise 保留原文)。
  B. 尚未入库的有价值长文: 走主同步管线 (transcribe 遇 article 会直接短路, 不需要 API Key)
     -> build_review -> build_approval -> promote。

用法:
    python backfill_articles.py plan            # 只打印计划
    python backfill_articles.py apply           # 执行(先整体备份知识库与账本)
    python backfill_articles.py apply --keep-noise
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from _paths import KB, LEDGER, ROOT, WORK, ensure_site_packages_on_path  # noqa: E402

ensure_site_packages_on_path()

import douyin_favorites_knowledge.cli as cli  # noqa: E402
from douyin_favorites_knowledge.config import default_config_path, load_config  # noqa: E402
from douyin_favorites_knowledge.workflow import (  # noqa: E402
    atomic_write_json, build_approval, build_review, promote,
)

ARTICLES = WORK / "articles_full.json"
OUTDIR = WORK / "article_backfill"
OBSERVED_AT = "2026-09-10T04:10:00+00:00"
NOISE_MARK = "> ⚠️ 该帖为抖音长文：`video.play_addr` 指向背景音乐，原 ASR 转录被识别为噪声，已忽略。正文见下方「## 文章正文」。"

# 未选中但有价值的长文 -> 入库(排除: 2 条三角洲游戏 + 1 条情感话题)
NEW_IDS = [
    "7619978677258048355",  # 一号大臣 agent set
    "7642572070500535587",  # 实用 Prompt: 边听故事边学东西
    "7643077636541091126",  # 万字长帖: 一本书是如何诞生的
    "7643384331763190857",  # VibeCoding: PaperSpine3 上线
    "7644919412230868265",  # 快速进入做事状态的方法
    "7652195710612861894",  # 没人教过你怎么做研究
    "7652607663401864458",  # AI 时代必读的 10 本书
    "7659350403963768102",  # 怎样判定自己是否接受了系统的学术训练
    "7661832842175337545",  # Codex 值得养成的收尾习惯
    "7676477047247047990",  # 博士如何把课题经费变成资产
    "7681173862700917498",  # 如何找到自己擅长并喜欢的领域
]
EXCLUDED_IDS = {
    "7635342954923626854": "三角洲改枪(游戏)",
    "7671707424666985849": "三角币兑换(游戏)",
    "7671964455109987584": "情感话题(渣男/恋爱)",
}


def load_articles() -> dict[str, dict]:
    data = json.load(open(ARTICLES, encoding="utf-8"))
    return {a["aweme_id"]: a for a in data["articles"]}


def kb_have() -> set[str]:
    return {f[11:-3] for f in os.listdir(KB) if f.startswith("collection-") and f.endswith(".md")}


def is_noise(text: str) -> bool:
    t = (text or "").strip()
    return (not t) or ("🎼" in t) or t.startswith("未获得语音转录") or len(t) <= 3


def add_frontmatter(text: str, kv: dict[str, str]) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    if end < 0:
        return text
    head = text[: end + 1]  # 含结尾换行
    tail = text[end + 1 :]
    existing = head
    add = []
    for k, v in kv.items():
        if re.search(r"^%s:" % re.escape(k), head, re.M):
            continue
        add.append('%s: %s' % (k, json.dumps(v, ensure_ascii=False)))
    if not add:
        return text
    return existing + "\n".join(add) + "\n" + tail


def merge_note(text: str, art: dict, keep_noise: bool) -> str:
    md = (art.get("markdown") or "").strip()
    out = add_frontmatter(text, {"content_source": "article", "article_id": art.get("article_id") or ""})

    # 噪声转录 -> 说明行
    if not keep_noise:
        def _repl(m: re.Match) -> str:
            body = m.group(2)
            if is_noise(body):
                return m.group(1) + NOISE_MARK + "\n\n"
            return m.group(0)

        out = re.sub(r"(### 转录\n\n)(.*?)(?=\n## )", _repl, out, flags=re.S)

    # 插入文章正文(位于 ## Source 之前)
    block = "## 文章正文\n\n"
    if art.get("article_title"):
        block += "> %s\n\n" % art["article_title"]
    block += md + "\n\n"
    if "\n## Source\n" in out:
        out = out.replace("\n## Source\n", "\n" + block + "## Source\n", 1)
    else:
        out = out.rstrip() + "\n\n" + block
    return out


def cmd_plan(arts: dict[str, dict], have: set[str]) -> None:
    in_kb = [a for a in arts if a in have]
    new = [a for a in NEW_IDS if a in arts]
    print("=" * 76)
    print("A. 已入库需回填正文: %d 条" % len(in_kb))
    for a in sorted(in_kb, key=lambda x: -len(arts[x]["markdown"])):
        print("   %s | %6d 字 | %s" % (a, len(arts[a]["markdown"]), (arts[a]["desc"] or "")[:40]))
    print()
    print("B. 未入库、本次新增: %d 条" % len(new))
    for a in new:
        print("   %s | %6d 字 | %s" % (a, len(arts[a]["markdown"]), (arts[a]["desc"] or "")[:40]))
    print()
    print("C. 未入库、仍不补: %d 条" % len(EXCLUDED_IDS))
    for a, why in EXCLUDED_IDS.items():
        print("   %s | %s" % (a, why))
    tot = sum(len(arts[a]["markdown"]) for a in in_kb + new)
    print()
    print("合计 %d 条, 正文 %d 字" % (len(in_kb) + len(new), tot))
    print("=" * 76)


def cmd_apply(arts: dict[str, dict], have: set[str], keep_noise: bool) -> None:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    OUTDIR.mkdir(parents=True, exist_ok=True)
    # 备份
    vault_backup = OUTDIR / ("vault_backup_" + ts)
    shutil.copytree(KB, vault_backup)
    ledger = LEDGER
    shutil.copy2(ledger, OUTDIR / ("ledger_backup_%s.sqlite3" % ts))
    print("已备份知识库 -> %s" % vault_backup, flush=True)
    print("已备份账本   -> %s" % (OUTDIR / ("ledger_backup_%s.sqlite3" % ts)), flush=True)

    # A. 合并回填
    merged, skipped, word_added = [], [], 0
    for a in sorted(arts):
        if a not in have:
            continue
        p = KB / ("collection-%s.md" % a)
        text = p.read_text(encoding="utf-8")
        if "## 文章正文" in text:
            skipped.append(a)
            continue
        new_text = merge_note(text, arts[a], keep_noise)
        p.write_text(new_text, encoding="utf-8")
        merged.append(a)
        word_added += len(arts[a]["markdown"])
    print("\n[A] 已回填 %d 条 (跳过 %d 条已含正文), 新增正文 %d 字" % (
        len(merged), len(skipped), word_added), flush=True)

    # B. 新条目走主管线
    cfg = load_config(default_config_path())
    raws = []
    for a in NEW_IDS:
        art = arts.get(a)
        if not art or a in have:
            continue
        title = (art["desc"] or "").splitlines()[0].strip() if art["desc"] else ""
        raws.append({
            "aweme_id": a,
            "title": art.get("article_title") or title or ("Douyin favorite %s" % a),
            "description": art.get("desc") or "",
            "author": art.get("author") or "",
            "source": "collection",
            "observed_at": OBSERVED_AT,
            "article": {
                "markdown": art["markdown"],
                "article_id": art.get("article_id") or "",
                "title": art.get("article_title") or title,
            },
        })
    promoted = 0
    if raws:
        staged = cli._apply_configured_stages(raws, cfg)
        manifest = build_review(cfg, staged, "backfill:articles")
        items = manifest.get("items", [])
        print("[B] review: %s" % json.dumps(manifest["summary"], ensure_ascii=False), flush=True)
        if items:
            runtime = cfg.ledger_path.parent / "article_backfill"
            runtime.mkdir(parents=True, exist_ok=True)
            rp, ap = runtime / "review.json", runtime / "approval.json"
            atomic_write_json(rp, manifest)
            atomic_write_json(ap, build_approval(rp, [it["aweme_id"] for it in items]))
            res = promote(cfg, rp, ap)
            promoted = res.get("promoted_count", 0)
            print("[B] promote: promoted=%s skipped=%s" % (promoted, res.get("skipped_count")), flush=True)
    print("\n完成: 回填 %d 条 + 新入库 %d 条" % (len(merged), promoted), flush=True)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "plan"
    keep_noise = "--keep-noise" in sys.argv
    arts = load_articles()
    have = kb_have()
    if mode == "plan":
        cmd_plan(arts, have)
    elif mode == "apply":
        cmd_apply(arts, have, keep_noise)
    else:
        raise SystemExit("unknown mode: %s" % mode)


if __name__ == "__main__":
    main()
