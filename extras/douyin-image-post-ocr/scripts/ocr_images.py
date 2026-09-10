# -*- coding: utf-8 -*-
"""对图文帖的原始图片做 OCR，把图里的文字抽出来。

用法:
    python ocr_images.py <aweme_id> [model]
    python ocr_images.py 7682744626328167034
    python ocr_images.py all Qwen/Qwen3-VL-30B-A3B-Instruct

依赖: ocr_test/meta_images.json (由 collect_images.py 生成)
"""
import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from _paths import WORK as ROOT  # noqa: E402

META = Path(os.environ.get("OCR_META") or (ROOT / "meta_images.json"))
IMG_DIR = ROOT / "images"
OUT_DIR = ROOT / "out"

# 注意：PaddleOCR-VL-1.5 在社交截图场景会重复退化（输出一长串 0000/emoji），
# 实测 Qwen3-VL 明显更稳，故默认用它。
DEFAULT_MODEL = "Qwen/Qwen3-VL-30B-A3B-Instruct"
ENDPOINT = "https://api.siliconflow.cn/v1/chat/completions"
PROMPT = "请逐字提取这张图片中的所有文字，严格保持原有顺序与换行。只输出文字本身，不要任何解释、标题或前后缀。"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


def download(url: str, dest: Path) -> bool:
    if dest.exists() and dest.stat().st_size > 0:
        return True
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": "https://www.douyin.com/",
        "Origin": "https://www.douyin.com",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as r, dest.open("wb") as f:
            f.write(r.read())
        return dest.stat().st_size > 0
    except Exception as e:
        print(f"    [下载失败] {type(e).__name__}: {e}", flush=True)
        return False


def ocr_one(path: Path, model: str, api_key: str) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    b64 = base64.b64encode(path.read_bytes()).decode()
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }],
        "temperature": 0,
        "max_tokens": 4096,
    }
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.loads(r.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        return f"[HTTP {e.code}] {e.read().decode('utf-8', errors='replace')[:300]}"
    except Exception as e:
        return f"[{type(e).__name__}] {e}"
    try:
        return (data["choices"][0]["message"]["content"] or "").strip()
    except Exception:
        return f"[解析失败] {json.dumps(data, ensure_ascii=False)[:300]}"


def process(item: dict, model: str, api_key: str, limit: int = 0) -> None:
    aid = item["aweme_id"]
    urls = item.get("images") or []
    if limit and limit > 0:
        urls = urls[:limit]
    folder = IMG_DIR / aid
    folder.mkdir(parents=True, exist_ok=True)
    print(f"\n{'='*70}\n{aid} | {item.get('author','')} | 共 {len(urls)} 张图", flush=True)
    print(f"标题: {(item.get('description') or '')[:80]}", flush=True)
    lines = [
        "---",
        f"aweme_id: \"{aid}\"",
        f"author: \"{item.get('author','')}\"",
        f"image_count: {len(urls)}",
        f"ocr_model: \"{model}\"",
        "---",
        "",
        f"# {(item.get('description') or aid)[:80]}",
        "",
        "## 图片文字 (OCR)",
        "",
    ]
    ok = 0
    for idx, url in enumerate(urls, 1):
        ext = ".jpeg"
        for cand in (".jpeg", ".webp", ".png", ".jpg"):
            if cand in url.split("?")[0].lower():
                ext = cand
                break
        dest = folder / f"{idx:02d}{ext}"
        if not download(url, dest):
            lines += [f"### 图 {idx}", "", "(图片下载失败)", ""]
            continue
        text = ocr_one(dest, model, api_key)
        ok += 1
        print(f"  图{idx}/{len(urls)} OCR完成 {len(text)} 字", flush=True)
        lines += [f"### 图 {idx}", "", text, ""]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{aid}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"  => 已写入 {out} (成功 {ok}/{len(urls)})", flush=True)


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return
    target = sys.argv[1]
    model = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_MODEL
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    api_key = os.environ.get("SILICONFLOW_API_KEY", "").strip()
    if not api_key:
        print("ERROR: 缺少 SILICONFLOW_API_KEY")
        return
    items = json.loads(META.read_text(encoding="utf-8"))
    img_items = [i for i in items if i.get("images")]
    if target == "all":
        picked = img_items
    else:
        picked = [i for i in img_items if i["aweme_id"] == target]
        if not picked:
            print(f"未在图文列表中找打 {target}；现有图文 {len(img_items)} 条")
            return
    print(f"模型: {model} | 待处理 {len(picked)} 条 | 每条上限 {limit or '不限'} 张", flush=True)
    for it in picked:
        process(it, model, api_key, limit)


if __name__ == "__main__":
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.pop(k, None)
    main()
