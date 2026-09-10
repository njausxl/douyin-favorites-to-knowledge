# -*- coding: utf-8 -*-
"""把 OCR 结果回填进 Obsidian 笔记。

- 先整体备份知识库到 ocr_test/backup_vault/
- 在每条笔记的「原始材料」之后插入「## 图片文字 (OCR)」
- 对图文帖的 ASR 噪声转录加一条警示，不删除原文

用法:
    python merge_ocr.py            # 预演(dry-run)，只报告不改
    python merge_ocr.py --apply    # 实际写入
"""
import json
import os
import re
import shutil
import sys
from pathlib import Path

from _paths import KB, WORK  # noqa: E402

OUT = Path(os.environ.get("OCR_OUT_DIR") or (WORK / "out"))
BACKUP = Path(os.environ.get("OCR_BACKUP") or (WORK / "backup_vault"))

MARKER = "## 图片文字 (OCR)"
WARN = ("> 本条为图文帖：音轨是背景音乐，下方 ASR 结果不可靠（多为噪声）。"
        "正文请见上方「图片文字 (OCR)」。")

NOISE_HINTS = ("🎼", "The number you have dialed", "Please leave your message")


def ocr_body(path: Path) -> str | None:
    text = path.read_text(encoding="utf-8")
    i = text.find(MARKER)
    if i < 0:
        return None
    return text[i + len(MARKER):].strip()


def looks_noise(transcript: str) -> bool:
    if len(transcript.strip()) < 80:
        return True
    return any(h in transcript for h in NOISE_HINTS)


def build(note_text: str, body: str, item: dict) -> str:
    lines = note_text.split("\n")
    # 1) frontmatter 增加 OCR 元信息
    if lines and lines[0].strip() == "---":
        end = next((k for k in range(1, len(lines)) if lines[k].strip() == "---"), None)
        if end:
            extra = [
                f'ocr_model: "{item.get("ocr_model", "")}"',
                f'image_count: {item.get("image_count", 0)}',
                'content_source: "image_ocr"',
            ]
            lines = lines[:end] + extra + lines[end:]

    text = "\n".join(lines)

    # 2) 转录加警示（仅图文噪声）
    def _warn(m: re.Match) -> str:
        block = m.group(0)
        if WARN in block:
            return block
        return "### 转录\n\n" + WARN + "\n" + block[len("### 转录"):]

    if re.search(r"^### 转录\s*$", text, flags=re.M):
        text = re.sub(r"^### 转录\s*\n(.*?)(?=^#{2,3} |\Z)", _warn, text, count=1, flags=re.M | re.S)

    # 3) 插入 OCR 段落：放在「## 研判」或「## Source」之前
    section = f"{MARKER}\n\n{body}\n"
    for anchor in ("## 研判", "## Source"):
        idx = text.find(anchor)
        if idx >= 0:
            return text[:idx].rstrip() + "\n\n" + section + "\n" + text[idx:].lstrip("\n")
    return text.rstrip() + "\n\n" + section


def main() -> None:
    apply = "--apply" in sys.argv
    items = json.loads((OUT.parent / "meta_selected.json").read_text(encoding="utf-8"))
    by_id = {i["aweme_id"]: i for i in items}

    done = sorted(p for p in OUT.glob("*.md"))
    print(f"OCR 产出 {len(done)} 个文件 | 模式: {'写入' if apply else '预演'}")

    if apply and not BACKUP.exists():
        print(f"备份知识库 -> {BACKUP}")
        shutil.copytree(KB, BACKUP, dirs_exist_ok=True)

    changed = skipped = 0
    for p in done:
        aid = p.stem
        note = KB / f"collection-{aid}.md"
        if not note.exists():
            print(f"  [跳过] 无对应笔记 {aid}")
            skipped += 1
            continue
        body = ocr_body(p)
        if not body:
            print(f"  [跳过] OCR 为空 {aid}")
            skipped += 1
            continue
        text = note.read_text(encoding="utf-8")
        if MARKER in text:
            print(f"  [跳过] 已含 OCR 段 {aid}")
            skipped += 1
            continue
        item = by_id.get(aid, {})
        item.setdefault("ocr_model", "Qwen/Qwen3-VL-30B-A3B-Instruct")
        item["image_count"] = body.count("### 图 ")
        new = build(text, body, item)
        if apply:
            note.write_text(new, encoding="utf-8")
        changed += 1
        print(f"  [{'写入' if apply else '将改'}] {aid} | 图 {item['image_count']} 张 | +{len(new)-len(text)} 字符")

    print(f"\n完成: 变更 {changed} 条，跳过 {skipped} 条")
    if not apply:
        print("这是预演。确认无误后加 --apply 实际写入。")


if __name__ == "__main__":
    main()
