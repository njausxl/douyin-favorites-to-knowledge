---
name: douyin-image-post-ocr
description: '抖音收藏内容补全：把只存在于图片里的正文（图文帖 OCR）和只存在于抖音长文里的正文抽出来，写入 Obsidian 笔记。

  四种用法：(A) 已内置进主同步管线，sync 时自动对图文帖走 OCR、对长文走正文接口，无需手工干预；
  (B) 存量图文帖批量补全，用手工三步流程处理历史遗留笔记；
  (C) 把当初被筛掉的误筛图文帖批量补录进库（复用主管线，自动 OCR）；
  (D) 抖音「长文(文章)」正文补全（aweme_type=163，走 aweme/detail 接口，零 API 成本）。

  适用场景：douyin-favorites-to-knowledge 同步后笔记只有标题/描述、正文缺失，或转录是背景音乐幻觉出的噪声（🎼 开头）。

  触发词：图文帖、图文 OCR、图片文字、抖音收藏没内容、转录是乱码、补全笔记、自动 OCR、误筛回捞、批量补录、长文、文章正文、aweme_type 163。

  仅处理图文帖与长文；普通口播视频走 ASR 即可。

  '
version: 1.4.0
agent_created: true
metadata:
  author: WorkBuddy
  platforms:
    - workbuddy
    - script
---

# 抖音图文帖 OCR

## 背景：为什么需要这个能力

`douyin-favorites-to-knowledge` 原本只有**语音识别（ASR）一条通道**，没有 OCR：

- 采集器只取 `aweme_id / desc / author / video.play_addr / duration`，**不取 `item.images`**。
- 图文帖没有真正的视频流，抖音把 `video.play_addr` 填成了**背景音乐 MP3**。
- 于是 ASR 对着 BGM 跑，产出幻觉垃圾（`🎼你生看。`、`🎼嗯。。🎼的都荡。The number you dialed...`），状态却标成 `success`。
- 结果：**正文全在图片里，笔记里一个字都没有，还混进了噪声。**

## 方式 A（已内置）：主同步管线自动 OCR

自 2026-09-10 起，OCR 已接进主流程，`sync` / `daily` / `scan` 会自动识别图文帖并走视觉模型，**无需手工干预**。

### 改动位置（site-packages 与 src/ 两份都改，重装不丢）

| 文件 | 改动 |
|---|---|
| `browser_collector.py` | 采集 JS 多取 `item.images`；`_source_item` 透传 `images`（非空才带） |
| `siliconflow.py` | 新增 `_image_urls / _download_image / _ocr_image / _transcribe_images`；`transcribe()` 开头分流：有 `images` 走 OCR，否则走 SenseVoice ASR |
| `workflow.py` | 新增 `_ocr_payload()`；`normalize_item` 挂载 `item["ocr"]`；`render_note` 渲染 `## 图片文字 (OCR)`；`validate_review` 放行 `ocr` 字段 |
| `cli.py` | `_apply_configured_stages` 对**已入库的图文帖**直接剔除，跳过冗余 OCR |

### 关键设计（踩过的坑）

1. **`ocr` 不参与 `content_sha256`**。它在 hash 计算之后挂载，`validate_review` 的 base 也不含它。否则换模型 / 换个措辞重跑 OCR 就会触发 `promoted item changed` 报错。
2. **已入库图文帖必须从本次运行剔除**。改版前入库的图文帖，其 ledger hash 基于 BGM 噪声转录；改版后跳过 ASR 就再也复现不出那个 hash。若保留会直接报 `promoted item changed`。剔除后既不报错，也省下一次付费 OCR。
3. **OCR 路径不写 `transcript`**，只写 `ocr.text`，渲染成独立段落，与语音转录互不污染。

### 可调开关（环境变量）

| 变量 | 默认 | 作用 |
|---|---|---|
| `DOUYIN_OCR_ENABLED` | `1` | 设 `0` 关闭自动 OCR |
| `DOUYIN_OCR_MODEL` | `Qwen/Qwen3-VL-30B-A3B-Instruct` | 视觉模型 |
| `DOUYIN_OCR_MAX_IMAGES` | `0`（不限） | 单条最多处理几张图 |
| `DOUYIN_OCR_CONCURRENCY` | `4` | 单条内并发张数（上限 8） |
| `DOUYIN_OCR_URL` | SiliconFlow chat/completions | 自定义端点 |

也可在 config 的 `transcription.options.ocr_model` 覆盖模型。

### 验证

```bash
# 离线回归（渲染 / hash 幂等 / schema 校验），路径按实际 venv 调整
$VENV "$SKILL_DIR/scripts/test_integration.py"
```

## 路径配置（换机器必读）

所有脚本共用 `scripts/_paths.py` 解析路径，**环境变量优先；未设置时按默认布局自动探测**。脚本里没有任何硬编码的机器路径，换机器不用改代码。

| 环境变量 | 含义 | 默认值 |
|---|---|---|
| `DOUYIN_OCR_ROOT` | 工作根目录 | 自动探测 `~/OneDrive/douyin`，退回 `~/douyin` |
| `DOUYIN_UPSTREAM` | 上游项目目录 | `$DOUYIN_OCR_ROOT/douyin-favorites-to-knowledge` |
| `DOUYIN_SITE_PACKAGES` | 打过补丁的 site-packages | `$DOUYIN_UPSTREAM/.venv/**/site-packages` |
| `DOUYIN_OCR_WORK` | 中间产物目录 | `$DOUYIN_OCR_ROOT/ocr_test` |
| `DOUYIN_OCR_KB` | Obsidian 知识库目录 | `~/OneDrive/Apps/Obsidian library/抖音知识库` |
| `DOUYIN_OCR_LEDGER` | 账本 sqlite3 文件 | `%APPDATA%/douyin-favorites-to-knowledge/state/ledger.sqlite3` |

**上工前先自检**——它会打印 6 个路径并标注 `OK` / `MISS`：

```bash
$VENV "$SKILL_DIR/scripts/_paths.py"
```

显示 `MISS` 的项用对应环境变量覆盖即可，不必改脚本。

## 脚本清单

| 脚本 | 作用 | 网络/费用 |
|---|---|---|
| `_paths.py` | 统一路径解析（自检用） | 无 |
| `collect_images.py` | 扩展采集，抓图文帖 `images` 列表 → `meta_images.json` | 无（本地浏览器） |
| `ocr_images.py` | 批量图片 OCR → `out/{aweme_id}.md` | **有**（VLM 按量计费） |
| `merge_ocr.py` | 把 OCR 结果回填进已有笔记（`--apply` 才写） | 无 |
| `backfill_misfiltered.py` | 误筛图文帖批量补录进库（复用主管线，自动 OCR） | **有** |
| `backfill_report.py` | 生成误筛补录报告 | 无 |
| `collect_articles.py` | 采集长文列表（正文被截断在 499 字） | 无 |
| `fetch_article_full.py` | 走 `aweme/detail` 取长文全文 | 无 |
| `backfill_articles.py` | 长文正文回填 + 入库 | 无（不调模型） |
| `report_articles.py` | 生成长文补全报告 | 无 |
| `test_integration.py` | 离线回归：渲染 / hash 幂等 / schema 校验 | 无 |

所有带 `plan` 子命令的脚本，`plan` 模式**只打印计划、不发网络请求**，可以先跑它确认名单再执行。

## 方式 B：存量批量补全（手工三步）

用于历史遗留笔记（方式 A 上线前入库的图文帖）。设 `$VENV` = venv python，`$WORK` = 工作目录。

### 第 1 步：扩展采集，拿到图片列表

```bash
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy   # 代理没开时必须清
$VENV "$SKILL_DIR/scripts/collect_images.py"
```

产出 `$WORK/meta_images.json`，`images` 非空即为图文帖。复用已登录 profile（`%LOCALAPPDATA%\douyin-favorites-to-knowledge\browser-profile`）。

### 第 2 步：图片 OCR

```bash
export SILICONFLOW_API_KEY=...            # 只读环境变量，不落盘
$VENV "$SKILL_DIR/scripts/ocr_images.py" all Qwen/Qwen3-VL-30B-A3B-Instruct
```

图片走抖音 CDN，**必须带 `Referer: https://www.douyin.com/`**。结果写 `$WORK/out/{aweme_id}.md`，图片缓存 `$WORK/images/{aweme_id}/`（可断点续跑）。第三个参数限制每条张数，用于试跑。

### 第 3 步：回填笔记

```bash
$VENV "$SKILL_DIR/scripts/merge_ocr.py"           # 预演，只报告
$VENV "$SKILL_DIR/scripts/merge_ocr.py" --apply   # 实际写入（自动整体备份知识库）
```

回填动作：frontmatter 加 `ocr_model` / `image_count` / `content_source`；在 `## 研判` 或 `## Source` 前插入 `## 图片文字 (OCR)`；给噪声转录加警示但不删原文；`--apply` 前 `shutil.copytree` 整体备份。

## 方式 C：把被筛掉的图文帖批量补录进知识库

场景：收藏夹里有一批图文帖当初被筛选口径（如「去掉游戏/娱乐」）连坐剔除，事后发现属于**误筛**（AI/Skill/科研、读书/社科、自我提升等知识类），需要补进库。

**不要**用方式 B 的手工三步——直接复用主管线最省事，OCR 会自动触发。

```bash
export SILICONFLOW_API_KEY=...                       # 从用户级环境变量导出，不落盘
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy  # 代理没开时必做
$VENV "$SKILL_DIR/scripts/backfill_misfiltered.py" plan    # 只打印名单，不发网络请求
$VENV "$SKILL_DIR/scripts/backfill_misfiltered.py" run     # 执行（可断点续跑）
```

`run` 做的事：逐条 `cli._apply_configured_stages`（有 `images` 就自动走 Qwen3-VL OCR）→ 结果逐条落 `staged.jsonl` → 最后 `build_review` → `build_approval` → `promote` 原子入库。

**两个必须注意的点**：

1. **名单内嵌在脚本的 `PLAN` 字典里**（按主题分组），`EXCLUDED` 字典留档排除项与理由。换任务时改这两个字典即可，不要硬编码到别处。
2. **`description` 为空的条目必须排除**。`normalize_item` 要求 `title` 或 `description` 至少有一个非空，否则直接抛 `has no title or description`。

生成报告：

```bash
$VENV "$SKILL_DIR/scripts/backfill_report.py"   # → docs/疑似误筛补录报告.md
```

**实测基线（2026-09-10，49 条 / 252 张图）**：25 分钟跑完，≈6 秒/张（单条内并发 4，条目间串行）；OCR 产出 73,844 字。知识库 306 → 355 条，含 OCR 段 73 → 122 条，账本同步一致。

## 方式 D：抖音「长文（文章）」正文补全

抖音除了视频（`aweme_type=0`）和图文帖（`68`），还有一类 **长文/文章体裁：`aweme_type=163`、`media_type=43`**。

它和图文帖踩**同一个坑**：`video.play_addr` 指向 `obj/ies-music/*.mp3`（BGM），ASR 必然产出 `🎼…` 噪声，状态却标成 `success`。而正文既不在 `images` 里，也不在 `desc` 里。

两个关键事实：

| 接口 | 拿到的 `article_info.article_content.markdown` |
|---|---|
| 收藏列表 `collection` | **截断在 499 字**（只是预览） |
| **`aweme/detail`** | **完整正文** |

```bash
# 取全文（走 aweme/detail）
$VENV "$SKILL_DIR/scripts/fetch_article_full.py"

# 回填 + 入库（先整体备份知识库与账本）
$VENV "$SKILL_DIR/scripts/backfill_articles.py" plan
$VENV "$SKILL_DIR/scripts/backfill_articles.py" apply
```

`backfill_articles.py` 分两组处理：
- **已入库的** → 合并式回填：在 `## Source` 前插入 `## 文章正文`，把 BGM 噪声转录替换为说明行（`--keep-noise` 可保留原文）。
- **未入库的** → 走主管线（`transcribe()` 遇 `article` 直接短路，**不需要 API Key**）→ `promote`。

### 为什么必须走合并、不能重推

`promote` 的 `_promotion_plan` 有「**untracked note conflict**」保护：笔记文件已存在且内容与本次生成的不一致时直接报错。所以**删账本记录再重推是行不通的**（除非连笔记一起删）。已入库条目一律用合并回填。

### 管线接入点

| 文件 | 改动 |
|---|---|
| `browser_collector.py` | 采集 JS 增 `article_id` / `article_preview`；新增 `ARTICLE_DETAIL_JS`、`BrowserCollector.fetch_article()`、`_enrich_article()`（分页循环里补全文） |
| `workflow.py` | 新增 `_article_payload()`；`normalize_item` 挂 `item["article"]`；`render_note` 渲染 `## 文章正文`；`validate_review` 放行 `"article"` |
| `siliconflow.py` | `transcribe()` **最开头**命中 `article` 就返回 `transcript_status: not_requested`，不跑 ASR、不校验 Key |
| `cli.py` | 已入库长文同样从本轮剔除（与 images 同一条判断） |

同样遵守「**`article` 不参与 `content_sha256`**」。

### 又一个坑：`assert_safe_value` 会拦正文

`security.py` 的 `assert_safe_value` 会拦截 `sk-[A-Za-z0-9_-]{20,}`、`gh[oprsu]_…`、`<think>` / `<analysis>`、U+FFFD。技术类长文里可能有代码示例，**入库前先扫一遍正文**，命中就先脱敏。

**实测基线（2026-09-10，38 条长文）**：全文合计 143,512 字；回填 24 条 + 新入库 11 条，知识库 355 → 366 条。

## 模型选型（踩过的坑）

| 模型 | 表现 |
|---|---|
| `PaddlePaddle/PaddleOCR-VL-1.5` | ❌ 社交截图场景**重复退化**，输出一长串 `0000` 或 emoji 直到撞满 max_tokens |
| `Qwen/Qwen3-VL-30B-A3B-Instruct` | ✅ 干净还原正文、楼中楼评论、表格结构 |

**默认用 Qwen3-VL**，别迷信"专用 OCR 模型"。速度约 10 秒/张，200 张约 40 分钟。

## 常见问题

- **`promoted item changed`**：已入库条目的 hash 对不上。图文帖走方式 A 的剔除逻辑即可；其他情况说明笔记被手工改过而 ledger 未同步，需人工迁移。
- **下载失败 `IncompleteRead`**：抖音 CDN 偶发断流，重跑该条即可（已缓存的图片会跳过）。
- **`connect ECONNREFUSED 127.0.0.1:7890`**：环境里残留了没在跑的代理，先 `unset` 所有 proxy 变量。
- **只想处理特定条目**：`ocr_images.py <aweme_id> <model>`。
- **图文帖判定**：`play_url` 指向 `obj/ies-music` 且以 `.mp3` 结尾 ⇒ 几乎一定是图文帖。
- **报 `ModuleNotFoundError: No module named '_paths'`**：说明不是以「脚本文件路径」方式调用的（例如把代码粘进交互式解释器）。正确姿势是 `$VENV <skills目录>/scripts/xxx.py`。
- **想换 OCR 模型**：`ocr_images.py <target> <model>`，或设 `DOUYIN_OCR_MODEL`。别用 PaddleOCR-VL，社交截图会退化。
