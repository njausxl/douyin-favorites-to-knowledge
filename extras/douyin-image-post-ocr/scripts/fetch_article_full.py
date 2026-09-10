# -*- coding: utf-8 -*-
"""逐条调用 aweme/detail 接口，取回长文全文 markdown。

输入: ocr_test/articles.json (列表接口, 正文被截断在 499 字)
输出: ocr_test/articles_full.json (完整正文)
"""
import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from _paths import WORK, ensure_site_packages_on_path  # noqa: E402

ensure_site_packages_on_path()
from douyin_favorites_knowledge.browser_collector import BrowserCollector  # noqa: E402

SRC = WORK / "articles.json"
OUT = WORK / "articles_full.json"

JS = r"""async ({aweme}) => {
    const common = {
        device_platform: 'webapp', aid: '6383', channel: 'channel_pc_web',
        pc_client_type: '1', version_code: '170400', version_name: '17.4.0',
        cookie_enabled: 'true', platform: 'PC', downlink: '10',
        effective_type: '4g', round_trip_time: '50',
    };
    const url = 'https://www.douyin.com/aweme/v1/web/aweme/detail/?' +
        new URLSearchParams(Object.assign({}, common, {aweme_id: aweme})).toString();
    const r = await fetch(url, {method: 'GET', credentials: 'include'});
    if (!r.ok) return {ok: false, http: r.status};
    const j = await r.json();
    const d = j.aweme_detail;
    if (!d) return {ok: false, status_code: j.status_code};
    const ai = d.article_info || {};
    let c = null;
    try { c = JSON.parse(ai.article_content || '{}'); } catch (e) { c = null; }
    return {
        ok: true,
        aweme_id: String(d.aweme_id || ''),
        desc: d.desc || '',
        author: d.author ? d.author.nickname || '' : '',
        aweme_type: Number(d.aweme_type || 0),
        article_id: ai.article_id || '',
        article_title: ai.article_title || '',
        article_type: ai.article_type,
        read_time: ai.read_time,
        article_has_more: ai.has_more,
        abstract: (c && c.long_article_abstract) || '',
        markdown: (c && c.markdown) || '',
    };
}"""


class Detail(BrowserCollector):
    async def one(self, aid: str) -> dict:
        return await self._page.evaluate(JS, {"aweme": aid})


async def main() -> None:
    ids = [a["aweme_id"] for a in json.load(open(SRC, encoding="utf-8"))["articles"]]
    c = Detail(channel="chrome", source="collection")
    await c.open(headless=True)
    out: dict[str, dict] = {}
    try:
        await c.navigate()
        if not await c.authenticated():
            print("ERROR: 未登录", flush=True)
            return
        for n, aid in enumerate(ids, 1):
            rec = None
            for attempt in range(3):
                try:
                    rec = await c.one(aid)
                    if rec and rec.get("ok"):
                        break
                except Exception as exc:  # noqa: BLE001
                    rec = {"ok": False, "error": str(exc)}
                await asyncio.sleep(1.0 + attempt)
            if rec and rec.get("ok"):
                out[aid] = rec
                print("[%2d/%2d] %s | %6d 字 | %s" % (
                    n, len(ids), aid, len(rec.get("markdown") or ""),
                    (rec.get("desc") or "")[:34]), flush=True)
            else:
                print("[%2d/%2d] %s | FAILED %s" % (n, len(ids), aid, rec), flush=True)
            await asyncio.sleep(0.35)
    finally:
        await c.close()
    OUT.write_text(json.dumps({"collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               "articles": [out[k] for k in sorted(out)]},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    tot = sum(len(v["markdown"]) for v in out.values())
    print("\n成功 %d / %d | 正文总字数 %d | 已写入 %s" % (len(out), len(ids), tot, OUT), flush=True)


if __name__ == "__main__":
    for v in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.pop(v, None)
    asyncio.run(main())
