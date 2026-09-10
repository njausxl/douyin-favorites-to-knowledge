# -*- coding: utf-8 -*-
"""离线验证：OCR 接入 workflow 后的渲染 / hash 幂等 / schema 校验。"""
import os
import sys

from _paths import SITE_PACKAGES

sys.path.insert(0, str(SITE_PACKAGES))
from douyin_favorites_knowledge.workflow import normalize_item, validate_review  # noqa: E402

BASE = {
    "aweme_id": "7683065726889970954",
    "title": "Nature权威指南",
    "author": "生信数据人",
    "description": "Nature权威指南：Gap是比较出来的。",
    "transcript": "",
    "transcript_source": "siliconflow_vlm_ocr",
    "transcript_status": "success",
    "tags": [],
    "observed_at": "2026-09-10T02:00:00+00:00",
    "source": "collection",
    "images": ["https://p3-sign.douyinpic.com/x~tplv-1.webp"],
    "ocr": {
        "model": "Qwen/Qwen3-VL-30B-A3B-Instruct",
        "text": "### 图 1\n\nGap 是比较出来的：不要问有没有创新，要问比谁强。",
        "image_count": 1,
        "images_ok": 1,
    },
}

fail = 0


def check(name, cond):
    global fail
    print(("  PASS " if cond else "  FAIL ") + name)
    if not cond:
        fail += 1


print("=== 1) 带 OCR 的图文帖 ===")
item = normalize_item(dict(BASE))
note = item["note"]
check("note 含 OCR 段", "## 图片文字 (OCR)" in note)
check("note 含识别正文", "Gap 是比较出来的" in note)
check("note 含元信息行", "共 1 张图" in note and "Qwen/Qwen3-VL-30B-A3B-Instruct" in note)
check("无转录时不再输出旧提示", "未获得语音转录" not in note)
check("item 含 ocr 字段", item.get("ocr", {}).get("text", "").startswith("### 图 1"))

print("\n=== 2) hash 与 OCR 内容无关（幂等）===")
other = dict(BASE)
other["ocr"] = {"model": "别的模型", "text": "完全不同的文字", "image_count": 1, "images_ok": 1}
item_other = normalize_item(other)
check("换模型/换文字后 content_sha256 不变", item["content_sha256"] == item_other["content_sha256"])

print("\n=== 3) 无 OCR 的普通视频（向后兼容）===")
plain = dict(BASE)
plain["aweme_id"] = "7683065726889970955"
plain.pop("ocr")
plain.pop("images")
plain["transcript"] = "这是语音转录正文"
plain["transcript_source"] = "siliconflow_sensevoice"
item_plain = normalize_item(plain)
check("note 不含 OCR 段", "## 图片文字 (OCR)" not in item_plain["note"])
check("note 含转录段", "### 转录" in item_plain["note"])
check("item 不含 ocr 字段", "ocr" not in item_plain)

print("\n=== 4) OCR 文本为空时不写 ocr 字段 ===")
empty = dict(BASE)
empty["ocr"] = {"model": "m", "text": "   ", "image_count": 1, "images_ok": 0}
item_empty = normalize_item(empty)
check("空 OCR 被丢弃", "ocr" not in item_empty)
check("note 无 OCR 段", "## 图片文字 (OCR)" not in item_empty["note"])

print("\n=== 5) validate_review 接受含 ocr 的条目 ===")
review = {"schema_version": 1, "created_at": "t", "source_label": "t", "summary": {}, "items": [item, item_plain]}
try:
    validate_review(review)
    check("校验通过", True)
except Exception as exc:  # noqa: BLE001
    check(f"校验通过 (错误: {exc})", False)

print("\n=== 6) 篡改 ocr 文本会被校验拦下 ===")
tampered = dict(item)
tampered["ocr"] = dict(item["ocr"], text="被篡改的文本")
tampered["note"] = item["note"]  # note 未同步
try:
    validate_review({"schema_version": 1, "created_at": "t", "source_label": "t", "summary": {}, "items": [tampered]})
    check("应报错但通过了", False)
except ValueError:
    check("校验拦截成功", True)

print("\n--- 样例笔记（带 OCR）---")
print(note)

print(f"\n结果: {'全部通过' if fail == 0 else str(fail) + ' 项失败'}")
sys.exit(1 if fail else 0)
