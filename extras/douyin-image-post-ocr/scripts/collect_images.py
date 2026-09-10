# -*- coding: utf-8 -*-
"""扩展采集：在官方采集器基础上，额外抓取图文帖的 images 列表与 aweme_type。

产出 ocr_test/meta_images.json，用于后续图片下载 + OCR。
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
    BrowserCollector,
    COLLECTION_API_URL,
)

OUT = Path(os.environ.get("OCR_OUT") or (WORK / "meta_images.json"))
MAX_ITEMS = 1200

EXT_JS = r"""async ({apiUrl, cursor, count, source}) => {
    const params = new URLSearchParams({
        device_platform: 'webapp',
        aid: '6383',
        channel: 'channel_pc_web',
        cookie_enabled: String(navigator.cookieEnabled),
        browser_language: navigator.language || 'zh-CN',
        browser_platform: navigator.platform || '',
        browser_name: 'Chrome',
    });
    const body = new URLSearchParams({count: String(count), cursor: String(cursor)});
    const response = await fetch(apiUrl + '?' + params.toString(), {
        method: 'POST', credentials: 'include',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body: body.toString(),
    });
    if (!response.ok) return {ok: false, http_status: response.status};
    const data = await response.json();
    return {
        ok: data.status_code === 0,
        status_code: data.status_code,
        cursor: Number(data.cursor || 0),
        has_more: Boolean(data.has_more),
        items: (data.aweme_list || []).map(item => ({
            aweme_id: String(item.aweme_id || ''),
            description: item.desc || '',
            author: item.author ? item.author.nickname || '' : '',
            aweme_type: Number(item.aweme_type || 0),
            play_url: item.video && item.video.play_addr && item.video.play_addr.url_list ? item.video.play_addr.url_list[0] || '' : '',
            duration_seconds: Number(item.video && item.video.duration || 0) / 1000,
            image_count: (item.images || []).length,
            images: (item.images || []).map(function (img) {
                if (!img || !img.url_list || !img.url_list.length) return '';
                var list = img.url_list;
                var best = '';
                for (var i = 0; i < list.length; i++) {
                    var u = list[i] || '';
                    if (u.indexOf('.image') !== -1 || u.indexOf('.webp') !== -1) { best = u; break; }
                }
                return best || list[0] || '';
            }).filter(function (u) { return u; }),
        })),
    };
}"""


class ImageCollector(BrowserCollector):
    async def fetch_page_ext(self, *, cursor: int, count: int) -> dict:
        if self._page is None:
            raise ValueError("browser is not open")
        result = await self._page.evaluate(
            EXT_JS,
            {"apiUrl": COLLECTION_API_URL, "cursor": cursor, "count": count, "source": self.source},
        )
        if not isinstance(result, dict):
            raise ValueError("Douyin returned an invalid collection response")
        return result


async def main() -> None:
    collector = ImageCollector(channel="chrome", source="collection")
    await collector.open(headless=True)
    try:
        await collector.navigate()
        if not await collector.authenticated():
            print("ERROR: 未登录，请先跑登录流程", flush=True)
            return
        observed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        collected: dict[str, dict] = {}
        cursor = 0
        seen: set[int] = set()
        while len(collected) < MAX_ITEMS:
            page_size = min(20, MAX_ITEMS - len(collected))
            result = await collector.fetch_page_ext(cursor=cursor, count=page_size)
            if not result.get("ok"):
                print("ERROR: 采集失败 status_code=", result.get("status_code"), flush=True)
                break
            items = result.get("items") or []
            for raw in items:
                aid = raw.get("aweme_id")
                if not aid:
                    continue
                raw["observed_at"] = observed_at
                collected[aid] = raw
            if not result.get("has_more") or not items:
                break
            nxt = int(result.get("cursor") or 0)
            if nxt in seen or nxt == cursor:
                break
            seen.add(cursor)
            cursor = nxt
            await asyncio.sleep(0.4)
        items = list(collected.values())
        OUT.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        img_items = [i for i in items if i.get("images")]
        print(f"采集完成: 共 {len(items)} 条，其中含图片列表(图文) {len(img_items)} 条", flush=True)
        print(f"已写入: {OUT}", flush=True)
        for i in img_items[:10]:
            print(f"  - {i['aweme_id']} | {i.get('author','')[:12]} | 图{i['image_count']}张 | {(i.get('description') or '')[:30]}", flush=True)
    finally:
        await collector.close()


if __name__ == "__main__":
    os.environ.pop("HTTP_PROXY", None)
    os.environ.pop("HTTPS_PROXY", None)
    os.environ.pop("http_proxy", None)
    os.environ.pop("https_proxy", None)
    asyncio.run(main())
