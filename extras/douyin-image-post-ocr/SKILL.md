---
name: douyin-image-post-ocr
description: '抖音收藏内容补全：把只存在于图片里的正文（图文帖 OCR）和只存在于抖音长文里的正文抽出来，写入 Obsidian 笔记。

  四种用法：(A) 已内置进主同步管线，sync 时自动对图文帖走 OCR、对长文走正文接口，无需手工干预；
  (B) 存量图文帖批量补全，用手工三步流程处理历史遗留笔记；
  (C) 把当初被筛掉的误筛图文帖批量补录进库（复用主管线，自动 OCR）；
  (D) 抖音「长文(文章)」正文补全（aweme_type=163，走 aweme/detail 接口，零 API 成本）；
  (E) 普通视频误筛审计与回捞：用文本模型逐条判定未入库视频，捞出被关键词筛选误伤的知识类；
  (F) 全量状态核查与转录深度审计：三方对照查缺口，并判断长视频是否被截断。

  适用场景：douyin-favorites-to-knowledge 同步后笔记只有标题/描述、正文缺失，或转录是背景音乐幻觉出的噪声（🎼 开头）；
  以及「收藏明明有 900+ 条，知识库只有几百条」这种缺口排查。

  触发词：图文帖、图文 OCR、图片文字、抖音收藏没内容、转录是乱码、补全笔记、自动 OCR、误筛回捞、批量补录、
  长文、文章正文、aweme_type 163、未完成的收藏、缺口核查、为什么没入库、转录被截断。

  '
version: 1.5.1
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
| `status_check.py` | 全量状态核查：知识库 / 账本 / 采集清单三方对照 | 无 |
| `transcript_depth.py` | 转录深度审计：按「字数÷秒数」找被截断的长视频 | 无 |
| `audit_videos.py` | 误筛审计：文本模型逐条判定未入库视频是否知识类 | **有**（文本模型，很便宜） |
| `backfill_videos.py` | 误筛视频批量回捞（名单外置 JSON，复用主管线自动分流） | **有**（按音视频时长） |
| `verify_segment.py` | 长视频切段转录的快速验证（只拉前 3 分钟试切，1 分钟验通全链路） | **有**（1 次 ASR，可忽略） |

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

## 方式 E：普通视频误筛审计与回捞

场景：收藏 900+ 条、知识库只有几百条，想知道**剩下的是漏做还是有意筛掉**。

**为什么会误筛**：筛选阶段常用「游戏/娱乐关键词」排除法，而关键词只看标题。抖音标题常是标签堆砌（`#健身 #增肌 #居家锻炼`）或信息很少，于是健身、心理、历史、哲学、理财这类内容被成批误伤。

### 第 1 步：三方对照，确认缺口分布

```bash
$VENV "$SKILL_DIR/scripts/status_check.py"
```

输出「图文帖 / 长文 / 普通视频」三类各自的已入库与未入库数。通常普通视频的未入库量最大。

### 第 2 步：确定知识库口径（**别自己猜**）

回捞前先查现有笔记的构成，用数据定口径：

```bash
cd "$KB" && grep -l -E "健身|训练|力量" collection-*.md | wc -l   # 各类各数一遍
```

如果库里已经有健身、装修、理财、中医养生等类目，说明是**宽口径**（只排除游戏 / 生活消费 / 纯娱乐），那这些未入库内容属于真误筛。

### 第 3 步：审计未入库视频

```bash
export SILICONFLOW_API_KEY=...
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy
$VENV "$SKILL_DIR/scripts/audit_videos.py" --limit 20   # 先小批量验证输出格式
$VENV "$SKILL_DIR/scripts/audit_videos.py"              # 全量，可断点续跑
```

逐条判定落 `$WORK/video_audit.jsonl`，知识类清单落 `$WORK/video_audit_keep.json`。
**模型判定会有误入**（例如把「三角洲超级优化」判成工具类），回捞前务必人工过一遍清单。

### 第 4 步：重新采集（**必须**）

`meta_images.json` 里的 `play_url` 是**签名地址，有效期约 2 小时**。隔天跑回捞会全部下载失败，所以：

```bash
$VENV "$SKILL_DIR/scripts/collect_images.py"    # 重新采集，刷新所有 URL
```

顺带能发现新增/取消的收藏（用 `collect_images.py` 前后两次结果 diff）。

### 第 5 步：回捞

名单外置成 JSON（分组只为可读；**执行顺序 = JSON 键序 + 组内顺序**）：

```json
{ "AI / 工具": ["7594078035163237659"], "健身 / 运动": ["7681635598053962681"] }
```

```bash
$VENV "$SKILL_DIR/scripts/backfill_videos.py" plan   plan.json      # 只打印，不发请求
$VENV "$SKILL_DIR/scripts/backfill_videos.py" status plan.json      # 进度，末行 TODO=<n>
$VENV "$SKILL_DIR/scripts/backfill_videos.py" run    plan.json 3    # 先跑 3 条验证
$VENV "$SKILL_DIR/scripts/backfill_videos.py" run    plan.json --asc
```

#### 短视频优先、长视频压后（`--asc`）

`--asc` 按时长升序执行。**这是长名单的默认姿势**，理由：

- 短视频单价低、条数多（实测 109 条 ≤5 分钟的片段合计仅 170 分钟素材），能在 `play_url` 有效窗口内先落袋；
- 长视频单条动辄十几分钟到半小时（580 分钟的《积极心理学》要下 2.45GB），放在最后即使撞上签名过期，重采集后补跑的代价也最小。

#### 长名单必须配多轮循环（否则必然烂尾）

`play_url` 约 2 小时过期，而 100 条以上的名单一轮跑不完（实测 176 条的短/中段要 3 小时上下）。
所以正确姿势是「采集 → run → status」循环，**不要指望一条命令跑到底**：

```bash
for r in 1 2 3; do
  $VENV "$SKILL_DIR/scripts/collect_images.py"                  # 刷新 URL
  $VENV "$SKILL_DIR/scripts/backfill_videos.py" run $PLAN --asc # 断点续跑
  TODO=$($VENV "$SKILL_DIR/scripts/backfill_videos.py" status $PLAN | sed -n 's/^TODO=//p')
  [ "$TODO" = "0" ] && break
done
```

`run` 的 `todo` 判定已把 `failed / too_large / unavailable / budget_exceeded` 视为「待处理」，
所以**重新采集后直接重跑即可自动补回失败项，不需要手工删 `staged.jsonl` 的行**。
（旧版脚本用 `a not in done` 过滤，失败项会被永久跳过 —— 这个坑已在 v1.5.1 修掉。）

长视频（30 分钟以上）单条可能要十几分钟到半小时（下载 + 抽音 + 上传 + 识别），**务必挂后台跑**。

#### 长名单分段：短/中 与 长 分开跑

一次性 212 条按「短视频 / 中视频 / 长视频」三段拆成独立名单分别跑，好处是每段有自己的收尾观测点，
且长视频段可以单独重新采集（不必为了它把短段的 URL 一起刷一遍）：

| 段 | 判据 | 条数（实测） | 素材时长 |
|---|---|---|---|
| A · 短视频 | < 5 分 | 109 | 170 分 |
| B · 中视频 | 5–20 分 | 67 | 662 分 |
| C · 长视频 | ≥ 20 分 | 36 | 2839 分 |

**下长视频前先估体积**：从 `play_url` 里抠 `br=` 参数，按 `秒数 × br ÷ 8 ÷ 1024` 估 MB。
实测 36 条长视频合计约 **16.9GB**，其中 2 条超 2GB —— 所以 `max_media_bytes` 要按最大的一条设，别只设 2GB。

#### 分段串行靠启动命令自己串联 —— 判断时别只看子进程命令行

`run_batch_loop.sh` 一次只接**一个** plan（`$1`），两段要靠启动命令串起来：

```bash
bash run_batch_loop.sh plan_batch2_ab.json 10
bash run_batch_loop.sh plan_batch2_c.json 10
```

**踩过的坑（2026-09-15，代价大）：只看子进程命令行就下结论。**
`ps -ef` 当时只显示 `run_batch_loop.sh plan_batch2_ab.json 10`，于是误判「启动时压根没带 C 段」，
另写了一个 relay 脚本（`kill -0` 轮询等 AB 退出后再起 C），
结果和外层本来就有的阶段二**同时跑了两份 C 段**（15:07:46 与 15:07:55 各起一个）。

真相藏在**外层命令**里。查它的正确位置是任务本身（`TaskOutput` 能看到完整命令与全部 stdout），
或者沿父进程链往上追到底；`ps -ef` 看到的永远只是当前正在跑的那一段。
**并发期虽然没写坏账本（`staged.jsonl` 校验 0 坏行），但纯属运气，不要复制这种做法。**

**绝不要并行启动两段**：两个进程会同时跑 `collect_images.py`（同写 `meta_images.json`）
并同时写 `staged.jsonl`，把账本和采集快照一起写坏。

**实测两段耗时（212 条，2026-09-15/16）**：

| 段 | 条数 | 轮数 | 起止 | 耗时 | 结果 |
|---|---|---|---|---|---|
| A+B | 175 | 7 | 08:43 → 15:07 | 6.4 h | 175/175 |
| C | 36 | 10 | 15:07 → 次日 07:09 | 15.4 h | 33/36 |

C 段单条最长耗时 **39 分钟**（2 小时视频，`elapsed 23575s` 是整轮累计）；
两条 2 小时级的视频各产出 3.6–4.0 万字正文。**整批 212 条总共约 22 小时**，
所以这类作业必须挂后台过夜，不要守着等。

#### 单条永久失败的条目要从名单里摘掉

`unavailable` 同样在 `RETRYABLE` 里，所以**一条永远救不回的条目会让 `TODO` 永不归零**，
多轮循环持续空转到轮次上限，白白拖住后续分段。实测那条是 5.9 秒的短视频
（`7574295280645264057`，连续三轮 `failed → unavailable`，重采集后仍拿不到可用地址）。

判定与处置：

- 同一条连续 ≥3 轮均为 `failed / unavailable`，且重新采集后仍失败 → 判为源头失效；
- **先备份 plan**，再从 plan 中剔除该 id，另存 `plan_batch2_excluded.json` 保留完整字段以便日后复查；
- 剔除后 `status` 应立即变为 `TODO=0`，循环正常收尾。

注意：**别用 `curl` 直接打 `play_url` 来判断失效** —— 抖音 CDN 对裸请求一律回 `403`
（已成功下载过的对照组地址同样是 403），这个测法没有任何区分度，会误导判断。
判定依据只能是回捞脚本自己跑出来的 `transcript_status`。

#### 超长视频：切段转录（已实现，2 小时以上自动生效）

C 段最后卡住的 3 条全是超长视频，反复重试 8 轮无一成功：

| aweme_id | 时长 | 原状态 | 说明 |
|---|---|---|---|
| `7479792365641813258` | 2.5 h | failed | 422 位皇帝 |
| `7571479934070263074` | 8.8 h | too_large | 战国时代，视频流按 `br×时长` 估约 14.6 GB |
| `7475276578130267430` | 9.7 h | failed | 《积极心理学》上 |

**两个失败原因，一个解法**：

- 两条 `failed` 是**下载成功后**在 ASR 阶段挂掉 —— 超长音频超出 SenseVoice 单次请求上限。
  当前管线对 ≤2 小时稳定可用（2 小时视频实测产出 3.6–4.0 万字）；
- `too_large` 那条不是识别问题，是**下载上限**：视频流 14.6 GB，把 `max_media_bytes`
  提到多少都不现实。

所以对长视频**不再下载视频流**，改为让 ffmpeg 直接拉签名 URL、只留音频、按时长切段：

```bash
ffmpeg -headers "Referer: https://www.douyin.com/" \
       -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 10 \
       -i "<play_url>" -vn -ac 1 -ar 16000 -b:a 64k \
       -f segment -segment_time 1800 -reset_timestamps 1 part-%03d.mp3
```

一举解决两件事：8 小时视频只落 ~250 MB 音频（而非十几 GB 视频），且每次上传都远在
ASR 长度上限内。各段独立转录后按顺序拼接。

**关键坑：本机 ffmpeg 不在 PATH 上。** `shutil.which("ffmpeg")` 返回空，于是老代码的
`_extract_audio()` **一直静默失败**，`_prepare_upload()` 回退成「直接上传原始视频文件」——
这既慢又容易在下载阶段撞上 `max_media_bytes`。真正可用的是 `imageio-ffmpeg` 自带的静态构建
（完整版：libmp3lame / http / https / `-reconnect` 都有）：

```
<venv>/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe
```

因此 `_ffmpeg_exe()` 的查找顺序是 **`DOUYIN_ASR_FFMPEG` → `PATH` → `imageio_ffmpeg.get_ffmpeg_exe()`**。

开关（均有默认值，通常不用改）：

| 环境变量 | 默认 | 含义 |
|---|---|---|
| `DOUYIN_ASR_SEGMENT_THRESHOLD_SECONDS` | `3600` | 超过这个时长才走切段 |
| `DOUYIN_ASR_SEGMENT_SECONDS` | `1800` | 每段音频时长（30 分钟） |
| `DOUYIN_ASR_FFMPEG` | 空 | 显式指定 ffmpeg 可执行文件 |

改动落在 `siliconflow.py`，新增 `_ffmpeg_exe()` / `_segment_settings()` /
`_stream_audio_segments()` / `_transcribe_parts()`，并在 `transcribe()` 里按
`item["duration_seconds"]` 分流。**src/ 与 venv 的 site-packages 两份都要同步**（见「改动位置」）。
切段成功的条目 `transcript_source` 为 `siliconflow_sensevoice_segmented`，并带
`segments_total` / `segments_ok` 两个字段。

**验证方式**：`verify_segment.py`（只拉前 3 分钟试切，几十秒就能验通「拉流 → 切段 → 上传」全链路），
不必等 8 小时跑完才知道方案行不行。实测三条 URL 均返回码 0、正确切段、首段转录内容准确。

**`too_large` 不是内容问题，是下载上限**：上游默认 `max_media_bytes = 512MB`（`local_whisper.MAX_MEDIA_BYTES` / `siliconflow.MAX_MEDIA_BYTES`，`cli.py` 生成默认配置时也写死这个值）。
码率高的长视频（如 80 分钟访谈，`br≈1783` ⇒ 约 1GB）会在下载阶段就被截断，报 `too_large`，**与 ASR 无关**。
放开办法是改用户配置（`%APPDATA%\douyin-favorites-to-knowledge\config.json`，Linux/macOS 在 `~/.config/`）：

```json
"transcription": { "options": { "max_media_bytes": 5368709120 } }
```

注意：这是**视频文件**上限，不是音频上限。下游 `_prepare_upload()` 会用 ffmpeg 把视频压成 `audio.mp3` 再上传，所以放开后 80 分钟的视频最终只上传几 MB 音频，不会真的推 1GB 上云。
阈值必须是正数（`config.py` 会校验 `> 0`，否则配置加载直接报错）。

**实测基线（2026-09-14）**：532 条未入库视频 → 审计出 246 条知识类（音视频合计 68.5 小时）；首批回捞 46 条（新增收藏知识类 13 + AI/工具/科研 33），**46 条全部入库**（图文帖 OCR 单条最高 18,118 字，视频 ASR 单条最高 38,663 字）。其中首轮 44 条直过，2 条失败 —— 1 条 `too_large`（80 分钟访谈，放开上限后成功，27,517 字）、1 条 `failed`（签名 URL 过期，重采集后成功）。**长视频务必留足时间：80 分钟访谈单条耗时约 20 分钟。**

## 方式 F：全量状态核查与转录深度审计

排查「为什么我的收藏没全进知识库」时的两把尺子。

### 1. 别把 `🎼` 当成转录失败

SenseVoice 的输出里经常出现 `🎼` —— 它是**音频事件标记**（音乐段 / 停顿），**不代表整篇是噪声**。
一条 8 小时公开课的转录里夹着几十个 `🎼` 是完全正常的。只看「有没有 `🎼`」会得出「121 条全是噪声」这种错误结论。

**真正的判据是信息密度**：

```bash
$VENV "$SKILL_DIR/scripts/transcript_depth.py"
```

它按「正文去梗后字数 ÷ 视频秒数」算密度：

| 密度 | 判断 |
|---|---|
| 3–6 字/秒 | 正常口播 |
| < 1.0 字/秒 | 疑似截断 / 下载失败 / ASR 空转 |

实测：51 条长视频密度中位数 6.12 字/秒，《周易概论》499.6 分钟 → 133,983 字，**零截断**。

### 2. 真正无正文的条目长什么样

「有 `未获得语音转录` 占位符 **且** 无 `## 图片文字 (OCR)` **且** 无 `## 文章正文`」——
三个条件同时成立才是真缺口。实测 366 条里只有 1 条（6 秒无声视频）。

## 模型选型（踩过的坑）

| 模型 | 表现 |
|---|---|
| `PaddlePaddle/PaddleOCR-VL-1.5` | ❌ 社交截图场景**重复退化**，输出一长串 `0000` 或 emoji 直到撞满 max_tokens |
| `Qwen/Qwen3-VL-30B-A3B-Instruct` | ✅ 干净还原正文、楼中楼评论、表格结构 |

**默认用 Qwen3-VL**，别迷信"专用 OCR 模型"。速度约 10 秒/张，200 张约 40 分钟。

## 常见问题

- **`promoted item changed`**：已入库条目的 hash 对不上。图文帖走方式 A 的剔除逻辑即可；其他情况说明笔记被手工改过而 ledger 未同步，需人工迁移。
- **转录状态 `too_large`**：下载阶段就超了 `max_media_bytes`（默认 512MB），**不是内容问题、和 ASR 无关**。按方式 E 第 5 步放开配置即可重跑。**别去调 ASR 模型或分段参数，方向就错了。**
- **转录状态 `failed`**：多半是 `play_url` 签名过期（约 2 小时）。重采集刷新 URL 后重跑该条。
- **下载失败 `IncompleteRead`**：抖音 CDN 偶发断流，重跑该条即可（已缓存的图片会跳过）。
- **`connect ECONNREFUSED 127.0.0.1:7890`**：环境里残留了没在跑的代理，先 `unset` 所有 proxy 变量。
- **只想处理特定条目**：`ocr_images.py <aweme_id> <model>`。
- **图文帖判定**：`play_url` 指向 `obj/ies-music` 且以 `.mp3` 结尾 ⇒ 几乎一定是图文帖。
- **报 `ModuleNotFoundError: No module named '_paths'`**：说明不是以「脚本文件路径」方式调用的（例如把代码粘进交互式解释器）。正确姿势是 `$VENV <skills目录>/scripts/xxx.py`。
- **想换 OCR 模型**：`ocr_images.py <target> <model>`，或设 `DOUYIN_OCR_MODEL`。别用 PaddleOCR-VL，社交截图会退化。
