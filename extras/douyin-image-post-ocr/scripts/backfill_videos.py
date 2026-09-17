# -*- coding: utf-8 -*-
"""把被误筛的普通视频批量补录进知识库（复用主同步管线，自动分流）。

分流逻辑由上游 `cli._apply_configured_stages` 负责：
    有 images  -> Qwen3-VL OCR
    有 article -> aweme/detail 取正文（零 API 成本）
    其余       -> SenseVoice ASR
然后 build_review -> build_approval -> promote，原子写入笔记 + 防重账本。

用法：
    python backfill_videos.py plan   <plan.json>            # 只打印名单，不发请求
    python backfill_videos.py status <plan.json>            # 进度；末行 TODO=<n>
    python backfill_videos.py run    <plan.json> [limit] [--asc]
                                                            # 执行（断点续跑）
    python backfill_videos.py commit                        # 用已有 staged 走 review/promote

**长名单（>50 条）建议配「采集 → run → status」多轮循环**：`play_url` 只有约 2 小时有效期，
一轮跑不完时，下一轮先重新采集刷新 URL，失败项会被自动补跑。参见 SKILL.md 方式 E 第 5 步。

`--asc` 按视频时长升序执行 —— 短视频优先、长视频压后。理由：
  - 短视频单价低、条数多，能在 `play_url` 有效窗口内先落袋；
  - 长视频单条动辄十几分钟到半小时，放在最后即便撞上 URL 过期，
    重采集后补跑的代价也最小（下一轮会自动补，无需手工清 staged）。

plan.json 格式（分组只为可读性；**执行顺序 = JSON 里的键序 + 组内顺序**）：
    {"短视频": ["7594078035163237659", "..."], "长视频": ["..."]}

⚠ 两个必须注意的点
1. **`play_url` 是签名地址，有效期约 2 小时** —— 采集后必须尽快跑；
   隔天执行会全部失败，先重新跑 `collect_images.py`。
2. **`description` 为空的条目要排除**（`normalize_item` 要求 title 或 description 至少一个非空）。
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import SITE_PACKAGES, WORK, ensure_site_packages_on_path  # noqa: E402

ensure_site_packages_on_path()

import douyin_favorites_knowledge.cli as cli  # noqa: E402
from douyin_favorites_knowledge.config import default_config_path, load_config  # noqa: E402
from douyin_favorites_knowledge.workflow import (  # noqa: E402
    atomic_write_json,
    build_approval,
    build_review,
    promote,
)

META = WORK / "meta_images.json"
OUT = WORK / "backfill_videos"
STAGED = OUT / "staged.jsonl"
RETRYABLE = {"failed", "unavailable", "too_large", "budget_exceeded"}
OBSERVED_AT = datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_plan(path: Path) -> tuple[dict, list]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    include = [aid for ids in plan.values() for aid in ids]
    return plan, include


def load_meta() -> dict:
    raw = json.loads(META.read_text(encoding="utf-8"))
    return {x["aweme_id"]: x for x in raw}


def build_raw(meta: dict, aid: str) -> dict:
    p = meta[aid]
    raw = {
        "aweme_id": aid,
        "title": p.get("title") or "",
        "description": p.get("description") or "",
        "author": p.get("author") or "",
        "duration_seconds": p.get("duration_seconds"),
        "source": "collection",
        "observed_at": OBSERVED_AT,
    }
    if p.get("images"):
        raw["images"] = p["images"]
    elif p.get("play_url"):
        raw["play_url"] = p["play_url"]
    return raw


def cmd_plan(meta: dict, plan: dict, include: list) -> None:
    print("=" * 82)
    total_min = 0
    for group, ids in plan.items():
        mins = sum((meta[a].get("duration_seconds") or 0) for a in ids) / 60
        total_min += mins
        print("\n【%s】%d 条 · %.0f 分钟" % (group, len(ids), mins))
        for a in ids:
            p = meta[a]
            kind = "图文帖" if p.get("images") else "视频"
            print("   %s | %-5s | %6.1f分 | %-12s | %s" % (
                a, kind, (p.get("duration_seconds") or 0) / 60,
                (p.get("author") or "")[:12],
                (p.get("description") or "").replace("\n", " ")[:38]))
    print("\n" + "-" * 82)
    print("合计 %d 条 · 音视频总时长约 %.0f 分钟（%.1f 小时）" % (len(include), total_min, total_min / 60))
    print("-" * 82)


def cmd_run(meta: dict, plan: dict, include: list, only: int | None = None, asc: bool = False) -> None:
    cfg = load_config(default_config_path())
    OUT.mkdir(parents=True, exist_ok=True)
    done = {}
    if STAGED.exists():
        for line in STAGED.read_text(encoding="utf-8").splitlines():
            if line.strip():
                it = json.loads(line)
                done[it["aweme_id"]] = it
    # 失败项（failed / too_large / unavailable / budget_exceeded）不进 done 的排除集，
    # 这样「重新采集刷 URL → 再跑一次」能自动补回，无需手工删 staged.jsonl 的行。
    todo = [a for a in include
            if a not in done or done[a].get("transcript_status") in RETRYABLE]
    if asc:
        # 短视频优先，长视频压后：URL 窗口内先吃掉便宜且数量多的条目
        todo.sort(key=lambda a: (meta[a].get("duration_seconds") or 0))
    if only:
        todo = todo[:only]
    retry_n = sum(1 for a in todo if a in done)
    print("名单 %d 条 | 已完成 %d | 本轮待处理 %d（其中补跑失败项 %d）" % (
        len(include), len(done), len(todo), retry_n), flush=True)
    if todo:
        est = sum((meta[a].get("duration_seconds") or 0) for a in todo) / 60
        print("待处理素材总时长 %.0f 分钟（%.1f 小时）" % (est, est / 60), flush=True)

    t0 = time.time()
    with STAGED.open("a", encoding="utf-8") as fh:
        for n, aid in enumerate(todo, 1):
            try:
                staged = cli._apply_configured_stages([build_raw(meta, aid)], cfg)[0]
            except Exception as exc:  # noqa: BLE001
                print("[%2d/%2d] %s  ERROR %s: %s" % (n, len(todo), aid, type(exc).__name__, exc), flush=True)
                continue
            done[aid] = staged
            fh.write(json.dumps(staged, ensure_ascii=False) + "\n")
            fh.flush()
            body = ""
            if staged.get("ocr"):
                body = staged["ocr"].get("text") or ""
            elif staged.get("article"):
                body = staged["article"].get("text") or ""
            else:
                body = staged.get("transcript") or ""
            print("[%2d/%2d] %s | %-12s | 正文 %6d 字 | elapsed %.0fs" % (
                n, len(todo), aid, staged.get("transcript_status"), len(body), time.time() - t0), flush=True)

    cmd_commit()


def cmd_status(meta: dict, plan: dict, include: list) -> None:
    """打印名单进度；末行 `TODO=<n>` 供 shell 循环判断是否需要再来一轮。"""
    done = {}
    if STAGED.exists():
        for line in STAGED.read_text(encoding="utf-8").splitlines():
            if line.strip():
                it = json.loads(line)
                done[it["aweme_id"]] = it
    todo = [a for a in include
            if a not in done or done[a].get("transcript_status") in RETRYABLE]
    ok = [a for a in include if a in done and done[a].get("transcript_status") not in RETRYABLE]
    bad = [a for a in todo if a in done]
    print("名单 %d | 已入库 %d | 待处理 %d（其中失败待补 %d）" % (
        len(include), len(ok), len(todo), len(bad)))
    for a in todo[:15]:
        st = done[a].get("transcript_status") if a in done else "(未处理)"
        print("   %s  %s" % (a, st))
    if len(todo) > 15:
        print("   ... 另 %d 条" % (len(todo) - 15))
    print("TODO=%d" % len(todo))


def cmd_commit() -> None:
    if not STAGED.exists():
        raise SystemExit("staged.jsonl 不存在，先跑 run")
    staged = [json.loads(l) for l in STAGED.read_text(encoding="utf-8").splitlines() if l.strip()]
    cfg = load_config(default_config_path())
    good = [it for it in staged if it.get("transcript_status") not in RETRYABLE]
    bad = [it["aweme_id"] for it in staged if it.get("transcript_status") in RETRYABLE]
    manifest = build_review(cfg, good, "backfill:videos")
    items = manifest.get("items", [])
    print("\n" + "=" * 82)
    print("review summary:", json.dumps(manifest["summary"], ensure_ascii=False))
    print("可提交 %d 条 | 重试类 %d 条 %s" % (len(items), len(bad), bad[:8]))
    if not items:
        print("无可提交条目，退出")
        return
    runtime = OUT / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    review_path, approval_path = runtime / "review.json", runtime / "approval.json"
    atomic_write_json(review_path, manifest)
    atomic_write_json(approval_path, build_approval(review_path, [it["aweme_id"] for it in items]))
    result = promote(cfg, review_path, approval_path)
    print("promote 结果: promoted=%s skipped=%s" % (
        result.get("promoted_count"), result.get("skipped_count")))
    print("=" * 82)


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "plan"
    if mode == "commit":
        cmd_commit()
        return
    if len(sys.argv) < 3:
        raise SystemExit("用法: backfill_videos.py <plan|run> <plan.json> [limit]")
    plan, include = load_plan(Path(sys.argv[2]))
    meta = load_meta()

    missing = [a for a in include if a not in meta]
    if missing:
        raise SystemExit("名单里存在 meta_images.json 中不存在的 id: %s" % missing)
    nolink = [a for a in include if not meta[a].get("images") and not meta[a].get("play_url")]
    if nolink:
        raise SystemExit("以下条目既无 images 也无 play_url（需重新采集）: %s" % nolink)
    empty = [a for a in include if not (meta[a].get("description") or meta[a].get("title"))]
    if empty:
        raise SystemExit("以下条目 title/description 均为空，无法成文: %s" % empty)

    if mode == "plan":
        cmd_plan(meta, plan, include)
    elif mode == "status":
        cmd_status(meta, plan, include)
    elif mode == "run":
        rest = [a for a in sys.argv[3:] if not a.startswith("-")]
        cmd_run(meta, plan, include,
                int(rest[0]) if rest else None,
                asc="--asc" in sys.argv[3:])
    else:
        raise SystemExit("unknown mode: %s" % mode)


if __name__ == "__main__":
    main()
