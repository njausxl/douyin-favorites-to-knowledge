# -*- coding: utf-8 -*-
"""采集抖音「长文/文章」类收藏(aweme_type=163)的正文 markdown。

article_info.article_content 是一个 JSON 字符串, 内含 markdown 与 long_article_abstract,
本脚本在浏览器里直接 JSON.parse 后取出, 产出 ocr_test/articles.json。
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from _paths import WORK, ensure_site_packages_on_path  # noqa: E402

ensure_site_packages_on_path()
from douyin_favorites_knowledge.browser_collector import (  # noqa: E402
    BrowserCollector, COLLECTION_API_URL,
)

OUT = Path(os.environ.get("OCR_OUT") or (WORK / "articles.json"))
MAX_ITEMS = 1200

JS = r"""async ({apiUrl, cursor, count}) => {
    const params = new URLSearchParams({
        device_platform: 'webapp', aid: '6383', channel: 'channel_pc_web',
        cookie_enabled: String(navigator.cookieEnabled),
        browser_language: navigator.language || 'zh-CN',
        browser_platform: navigator.platform || '', browser_name: 'Chrome',
    });
    const body = new URLSearchParams({count: String(count), cursor: String(cursor)});
    const response = await fetch(apiUrl + '?' + params.toString(), {
        method: 'POST', credentials: 'include',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body: body.toString(),
    });
    if (!response.ok) return {ok: false, http_status: response.status};
    const data = await response.json();
    const arts = [];
    for (const item of (data.aweme_list || [])) {
        if (Number(item.aweme_type) !== 163) continue;
        const ai = item.article_info || {};
        let content = null;
        try { content = JSON.parse(ai.article_content || '{}'); } catch (e) { content = null; }
        arts.push({
            aweme_id: String(item.aweme_id || ''),
            description: item.desc || '',
            author: item.author ? item.author.nickname || '' : '',
            aweme_type: Number(item.aweme_type),
            media_type: item.media_type,
            article_id: ai.article_id || '',
            article_title: ai.article_title || '',
            article_type: ai.article_type,
            article_abstract: (content && content.long_article_abstract) || '',
            markdown: (content && content.markdown) || '',
        });
    }
    return {ok: data.status_code === 0, status_code: data.status_code,
            cursor: Number(data.cursor || 0), has_more: Boolean(data.has_more), articles: arts};
}"""


class ArticleCollector(BrowserCollector):
    async def fetch_page_ext(self, *, cursor: int, count: int) -> dict:
        if self._page is None:
            raise ValueError("browser is not open")
        r = await self._page.evaluate(JS, {"apiUrl": COLLECTION_API_URL, "cursor": cursor, "count": count})
        if not isinstance(r, dict):
            raise ValueError("invalid response")
        return r


async def main() -> None:
    c = ArticleCollector(channel="chrome", source="collection")
    await c.open(headless=True)
    found: dict[str, dict] = {}
    try:
        await c.navigate()
        if not await c.authenticated():
            print("ERROR: 未登录", flush=True)
            return
        cursor, seen = 0, set()
        while len(found) < MAX_ITEMS:
            r = await c.fetch_page_ext(cursor=cursor, count=20)
            if not r.get("ok"):
                print("ERROR status_code=", r.get("status_code"), flush=True)
                break
            for a in r.get("articles") or []:
                found[a["aweme_id"]] = a
            if not r.get("has_more"):
                break
            nxt = int(r.get("cursor") or 0)
            if nxt in seen or nxt == cursor:
                break
            seen.add(cursor)
            cursor = nxt
            await asyncio.sleep(0.4)
    finally:
        await c.close()
    arts = sorted(found.values(), key=lambda x: x["aweme_id"])
    OUT.write_text(json.dumps({"collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               "articles": arts}, ensure_ascii=False, indent=2), encoding="utf-8")
    withmd = [a for a in arts if a["markdown"]]
    print("采集完成: 长文 %d 条, 其中有正文 markdown 的 %d 条" % (len(arts), len(withmd)), flush=True)
    print("正文总字数: %d" % sum(len(a["markdown"]) for a in arts), flush=True)
    for a in arts:
        print("   %s | %6d 字 | %s" % (a["aweme_id"], len(a["markdown"]), (a["description"] or "")[:40]), flush=True)
    print("已写入", OUT, flush=True)


if __name__ == "__main__":
    for v in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.pop(v, None)
    asyncio.run(main())
