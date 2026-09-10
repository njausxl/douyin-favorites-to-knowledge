# -*- coding: utf-8 -*-
"""生成长文正文补全报告 -> docs/长文正文补全报告.md"""
import json
import os
import re
import sys
from pathlib import Path

from _paths import KB, ROOT, WORK  # noqa: E402

sys.path.insert(0, str(WORK))
import backfill_articles as ba  # noqa: E402

arts = ba.load_articles()
have = {f[11:-3] for f in os.listdir(KB) if f.startswith("collection-") and f.endswith(".md")}
# B 组是本次新入库的; A 组是回填前就已在库里的(按 NEW_IDS 区分, 因为 promote 后两者都在库里了)
new = [a for a in ba.NEW_IDS if a in arts]
in_kb = sorted([a for a in arts if a in have and a not in set(new)], key=lambda x: -len(arts[x]["markdown"]))

L = ["# 抖音长文（文章）正文补全报告", "", "生成时间: 2026-09-10", "",
     "## 问题", "",
     "收藏夹里有 **38 条「长文」类内容**（`aweme_type=163`，抖音的文章体裁）。它们的：",
     "- `video.play_addr` 指向**背景音乐 MP3**，ASR 对着 BGM 跑 → 输出 `🎼…` 噪声，状态却标成 `success`；",
     "- 列表接口返回的 `article_info.article_content.markdown` **被截断在 499 字**。",
     "",
     "所以这些笔记原本只有标题 + 标题级描述，**正文一个字都没有**。", "",
     "## 解法", "",
     "正文其实由 `aweme/detail` 接口完整提供（`article_info.article_content.markdown`）。两条动作：",
     "",
     "1. **采集层**：`browser_collector.py` 识别 `article_id`，逐条调 detail 接口取全文；",
     "2. **渲染层**：`workflow.py` 新增 `## 文章正文` 段；`siliconflow.py` 遇 article 直接短路（不做 ASR，**不消耗 API**）。",
     "",
     "## 结果", "",
     "| 指标 | 数值 |",
     "|---|---|",
     f"| 长文总数 | {len(arts)} 条 |",
     f"| 回填正文（已入库） | **{len(in_kb)} 条** |",
     f"| 新增入库 | **{len(new)} 条** |",
     f"| 正文合计 | **{sum(len(arts[a]['markdown']) for a in in_kb + new):,} 字** |",
     f"| 仍不补 | {len(ba.EXCLUDED_IDS)} 条（游戏 / 情感话题）|",
     "",
     "### A. 已入库 · 回填正文", "",
     "| aweme_id | 作者 | 正文字数 | 标题 |", "|---|---|---|---|"]
for a in in_kb:
    L.append("| %s | %s | %s | %s |" % (a, (arts[a]["author"] or "")[:12],
                                        format(len(arts[a]["markdown"]), ","),
                                        (arts[a]["desc"] or "")[:34]))
L += ["", "### B. 未入库 · 本次新增", "",
      "| aweme_id | 作者 | 正文字数 | 标题 |", "|---|---|---|---|"]
for a in new:
    L.append("| %s | %s | %s | %s |" % (a, (arts[a]["author"] or "")[:12],
                                        format(len(arts[a]["markdown"]), ","),
                                        (arts[a]["desc"] or "")[:34]))
L += ["", "### C. 仍不补", "", "| aweme_id | 原因 |", "|---|---|"]
for a, why in ba.EXCLUDED_IDS.items():
    L.append("| %s | %s |" % (a, why))
L += ["", "## 笔记结构", "",
      "```",
      "---",
      "…",
      "transcript_source: article / none",
      "content_source: article      # 回填的 24 条加在 frontmatter",
      "---",
      "# 标题",
      "## 原始材料",
      "### 原始描述",
      "### 转录   → 噪声已替换为说明行",
      "## 文章正文   → 抖音原文 markdown（保留原格式）",
      "## Source",
      "```", "",
      "## 验证", "",
      "| 检查项 | 结果 |",
      "|---|---|",
      f"| 知识库笔记总数 | {len([f for f in os.listdir(KB) if f.startswith('collection-')])} |",
      f"| 含「## 文章正文」 | {len([f for f in os.listdir(KB) if f.startswith('collection-') and '## 文章正文' in open(KB/f, encoding='utf-8').read()])} |",
      f"| 含「## 图片文字 (OCR)」 | {len([f for f in os.listdir(KB) if f.startswith('collection-') and '## 图片文字 (OCR)' in open(KB/f, encoding='utf-8').read()])} |",
      "", "## 备份", "",
      "- 知识库整体备份: `ocr_test/article_backfill/vault_backup_*`",
      "- 账本备份: `ocr_test/article_backfill/ledger_backup_*.sqlite3`",
      "- 全文数据: `ocr_test/articles_full.json`（38 条，含完整 markdown）", ""]

out = ROOT / "docs" / "长文正文补全报告.md"
out.write_text("\n".join(L), encoding="utf-8")
print("已写入", out)
print("回填 %d + 新增 %d, 正文 %d 字" % (len(in_kb), len(new),
                                    sum(len(arts[a]["markdown"]) for a in in_kb + new)))
