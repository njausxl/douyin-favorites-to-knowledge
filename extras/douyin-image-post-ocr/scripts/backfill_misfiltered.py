# -*- coding: utf-8 -*-
"""把此前被误筛的图文帖(非游戏 / 非数码硬件 / 非本地生活消费 / 非纯娱乐)批量补录进知识库。

走的是集成后的主同步管线:
    cli._apply_configured_stages  ->  有 images 则自动调用 Qwen3-VL 做 OCR
    build_review -> build_approval -> promote   (原子写入笔记 + 防重账本)

用法:
    python backfill_misfiltered.py plan     # 只打印名单, 不做任何网络调用
    python backfill_misfiltered.py run      # 执行(可断点续跑: 结果逐条落 staged.jsonl)
    python backfill_misfiltered.py commit   # 仅用已有的 staged.jsonl 走 review/promote
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from _paths import ROOT, WORK, ensure_site_packages_on_path  # noqa: E402

ensure_site_packages_on_path()

import douyin_favorites_knowledge.cli as cli  # noqa: E402
from douyin_favorites_knowledge.config import default_config_path, load_config  # noqa: E402
from douyin_favorites_knowledge.workflow import (  # noqa: E402
    atomic_write_json,
    build_approval,
    build_review,
    promote,
)

OUT = WORK / "backfill"
OUT.mkdir(parents=True, exist_ok=True)
STAGED = OUT / "staged.jsonl"
RETRYABLE = {"failed", "unavailable", "too_large", "budget_exceeded"}
OBSERVED_AT = "2026-09-10T03:20:00+00:00"

# ── 补录名单: 只保留「有知识/信息价值」的图文帖 ─────────────────────────────
PLAN: dict[str, list[str]] = {
    "AI / 工具 / Skill / 科研": [
        "7594078035163237659",  # 用 GPT 做自我认知实验
        "7672690782151238778",  # skill 把照片变水墨画
        "7635227879882935793",  # 让 skill 像达尔文一样进化
        "7649205343028923657",  # 人文社科研究生硬核 skills
        "7634123474701103202",  # ChatGPT 一键复刻韩国造型师
        "7636010926693781227",  # build in public / 健身 Skill
        "7654859538114423028",  # codex 启动卡顿、占 C 盘的解决办法
        "7613697372111110312",  # 个人理解 prompt, 同样适用于 Gemini
        "7683065726889970954",  # Nature 权威指南: Research Gap 怎么找
        "7676940088823340115",  # AI 提示词 / ai 使用技巧
        "7677218637510359674",  # AI 提示词: 召唤十年后的自己
        "7676493491988369819",  # 把老师傅脑子里的经验"蒸馏"出来
        "7645689246305212278",  # 告别古法科研, 从十个 skill 开始
        "7636426029628064164",  # AI 效率工具
        "7635296166259490809",  # AI 时代个体创业框架
        "7635089603301422470",  # 走在第四次工业革命的前端
        "7631975728636734900",  # 学习 Agent 有感(操作系统类比)
        "7624122698792962673",  # claude code 源码架构剖析
        "7597845932876821989",  # 四大 AI: 站在新时代的起点
    ],
    "读书 / 社科 / 书单": [
        "7603346671796362330",  # 格物心法 · 读书摘录 · 手写随笔
        "7582566501903945009",  # 戳破男女相处迷雾的经典老书
        "7673130032689256009",  # INFJ 的作家书单推荐
        "7678975886406463139",  # 人生 100 本书单
        "7584608080621767951",  # #书单 · 置身事内好看吗
        "7680786981945042280",  # 十五本书让你读懂世界规律
        "7672214728559089829",  # 《负资产时代》日本经济停滞
        "7619742980215272934",  # 三本震撼你的社会学书
        "7605579069924682917",  # 三本震撼你的社会学书
        "7584653957000121610",  # 科层制的未来与消亡
    ],
    "自我提升 / 心理 / 认知": [
        "7625931507081091557",  # 提升表达力 · 口才训练
        "7661960638995361721",  # 看完鲁豫×姜思达后给自己做的问卷
        "7595980213465899194",  # 如何用两个小时规划 26 年
        "7681681789140139377",  # 思考笔记 · 强者思维逻辑 · 无效学习止损
        "7679765755168119781",  # 一些情绪解药
        "7680084615294871930",  # 先有证明自己的作品
        "7677430242273417715",  # 浮于表面的因果论赚不到钱
        "7666989003639503860",  # 切换九种视角看待问题
        "7669593636266746105",  # 心理防御机制 / 戒掉受害者心态
        "7668082098590451539",  # 如何克服严重的拖延症
        "7625701313007185546",  # 《Nature》前额叶 · ADHD 大脑养护
        "7511412223530257702",  # 长期坚持做好一件事的方法
        "7503870505478442278",  # 像农民一样思考 Think like a farmer
        "7482348910556597513",  # 人的行为多为满足情绪价值
    ],
    "学习 / 备考 / 语言": [
        "7633393824915587493",  # 教师编备考 · 教综背诵
        "7624063533131616763",  # 雅思备考技巧
        "7680559031904547813",  # 新概念英语
        "7631463104476019941",  # 遴选备考: 执着的力量
    ],
    "人文 / 地理科普": [
        "7682744626328167034",  # "一个贴吧老哥流浪的故事"续集(100 图)
        "7676779356332976482",  # 东北地区地形(地理)
    ],
}

INCLUDE = [aid for group in PLAN.values() for aid in group]

# 明确排除的条目(分类留档, 便于日后回溯)
EXCLUDED: dict[str, list[str]] = {
    "游戏(三角洲)": [
        "7655970351348926181", "7582545962394275131", "7585866953454669075",
        "7625473041200627698", "7586498777637309750", "7585888808340999470",
        "7585932510569139493", "7637506211490936945", "7614119209378893065",
        "7576912930043524210", "7594273158296921713", "7676634659345953785",
        "7603813789410135334", "7586073807905246507",
    ],
    "数码硬件": ["7562084196401220922"],
    "大连本地生活 / 旅游 / 美食": [
        "7583632541485681961", "7632562870551085947", "7579190271797524964",
        "7591876489211333541", "7625596940102200165", "7581722775225847077",
    ],
    "消费购物 / 生活技巧 / 纯娱乐": [
        "7634744550519383626", "7670110289009957553", "7632672317675684197",
        "7633070823473333925", "7579594942613583050", "7580881772142925666",
        "7573686157235902885", "7676906074561171301",
    ],
    "描述为空(无法成文)或内容不明": [
        "7644972882137413797", "7630637566509270449", "7622666866762553061",
    ],
}


def load_posts() -> dict[str, dict]:
    posts = json.load(open(ROOT / "ocr_test" / "meta_images.json", encoding="utf-8"))
    return {p["aweme_id"]: p for p in posts if p.get("images")}


def build_raw(posts: dict[str, dict], aid: str) -> dict:
    p = posts[aid]
    return {
        "aweme_id": aid,
        "title": p.get("title") or "",
        "description": p.get("description") or "",
        "author": p.get("author") or "",
        "images": p["images"],
        "duration_seconds": p.get("duration_seconds"),
        "source": "collection",
        "observed_at": OBSERVED_AT,
    }


def cmd_plan(posts: dict[str, dict]) -> None:
    print("=" * 78)
    print("拟补录(疑似误筛) 共 %d 条" % len(INCLUDE))
    print("=" * 78)
    total_img = 0
    for group, ids in PLAN.items():
        imgs = sum(posts[a]["image_count"] for a in ids)
        total_img += imgs
        print("\n【%s】%d 条 / %d 张图" % (group, len(ids), imgs))
        for a in ids:
            p = posts[a]
            print("   %s | 图%3d | %-12s | %s" % (
                a, p["image_count"], (p.get("author") or "")[:12],
                (p.get("description") or "").replace("\n", " ")[:34]))
    print("\n" + "-" * 78)
    print("拟补录合计: %d 条 / %d 张图" % (len(INCLUDE), total_img))
    print("\n明确排除: %d 条" % sum(len(v) for v in EXCLUDED.values()))
    for group, ids in EXCLUDED.items():
        print("   %s: %d 条" % (group, len(ids)))
    print("-" * 78)


def cmd_run(posts: dict[str, dict]) -> None:
    cfg = load_config(default_config_path())
    done: dict[str, dict] = {}
    if STAGED.exists():
        for line in STAGED.read_text(encoding="utf-8").splitlines():
            if line.strip():
                it = json.loads(line)
                done[it["aweme_id"]] = it
    todo = [a for a in INCLUDE if a not in done]
    print("已完成 %d / %d, 本轮待处理 %d 条" % (len(done), len(INCLUDE), len(todo)), flush=True)

    t0 = time.time()
    with STAGED.open("a", encoding="utf-8") as fh:
        for n, aid in enumerate(todo, 1):
            raw = build_raw(posts, aid)
            try:
                staged = cli._apply_configured_stages([raw], cfg)[0]
            except Exception as exc:  # noqa: BLE001
                print("[%2d/%2d] %s  ERROR %s: %s" % (n, len(todo), aid, type(exc).__name__, exc), flush=True)
                continue
            done[aid] = staged
            fh.write(json.dumps(staged, ensure_ascii=False) + "\n")
            fh.flush()
            ocr = staged.get("ocr") or {}
            body = (ocr.get("text") or "").strip()
            print("[%2d/%2d] %s | %-16s | OCR %d 字 | 图 %d/%d | elapsed %.0fs" % (
                n, len(todo), aid, staged.get("transcript_status"),
                len(body), ocr.get("images_ok", 0), ocr.get("image_count", 0),
                time.time() - t0), flush=True)

    try:
        cmd_commit(posts)
    except Exception as exc:  # noqa: BLE001
        print("COMMIT FAILED: %s: %s" % (type(exc).__name__, exc), flush=True)
        raise


def cmd_commit(posts: dict[str, dict]) -> None:
    if not STAGED.exists():
        raise SystemExit("staged.jsonl 不存在, 先跑 run")
    staged = [json.loads(l) for l in STAGED.read_text(encoding="utf-8").splitlines() if l.strip()]
    cfg = load_config(default_config_path())
    good = [it for it in staged if it.get("transcript_status") not in RETRYABLE]
    bad = [it["aweme_id"] for it in staged if it.get("transcript_status") in RETRYABLE]
    manifest = build_review(cfg, good, "backfill:misfiltered")
    items = manifest.get("items", [])
    print("\n" + "=" * 78)
    print("review summary:", json.dumps(manifest["summary"], ensure_ascii=False))
    print("可提交 %d 条 | 重试类 %d 条 %s" % (len(items), len(bad), bad[:8]))
    if not items:
        print("无可提交条目, 退出")
        return
    runtime = cfg.ledger_path.parent / "backfill"
    runtime.mkdir(parents=True, exist_ok=True)
    review_path = runtime / "review.json"
    approval_path = runtime / "approval.json"
    atomic_write_json(review_path, manifest)
    atomic_write_json(approval_path, build_approval(review_path, [it["aweme_id"] for it in items]))
    result = promote(cfg, review_path, approval_path)
    print("promote 结果: promoted=%s skipped=%s" % (
        result.get("promoted_count"), result.get("skipped_count")))
    print("=" * 78)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "plan"
    posts = load_posts()
    missing = [a for a in INCLUDE if a not in posts]
    if missing:
        raise SystemExit("名单里有 meta_images.json 中不存在的 id: %s" % missing)
    if mode == "plan":
        cmd_plan(posts)
    elif mode == "run":
        cmd_run(posts)
    elif mode == "commit":
        cmd_commit(posts)
    else:
        raise SystemExit("unknown mode: %s" % mode)


if __name__ == "__main__":
    main()
