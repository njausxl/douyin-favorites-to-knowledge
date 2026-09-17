# -*- coding: utf-8 -*-
"""长视频切段转录的快速验证：只拉前 3 分钟试切，几十秒验通全链路。

为什么需要它：超长视频单条要跑几十分钟到几小时，如果方案本身不可行
（CDN 拒绝裸拉流、`-f segment` 切不出段、切出的音频上传被拒），
等几小时才发现就太贵了。本脚本把这三点压缩到 1 分钟内验完。

用法：
    python verify_segment.py                    # 用内置的三条超长视频
    python verify_segment.py <aweme_id> [...]   # 指定条目
    python verify_segment.py --probe 600        # 改拉流时长（秒）
    python verify_segment.py --seg 120          # 改试切段长（秒）

退出码：0 全通；1 有任一条失败。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import WORK, ensure_site_packages_on_path  # noqa: E402

ensure_site_packages_on_path()

META = WORK / "meta_images.json"

# 2026-09 实测踩到的三条超长视频（2.5h failed / 8.8h too_large / 9.7h failed）
DEFAULT_TARGETS = [
    "7479792365641813258",
    "7475276578130267430",
    "7571479934070263074",
]


def probe(aweme_id: str, meta: dict, probe_seconds: int, seg_seconds: int) -> bool:
    import douyin_favorites_knowledge.siliconflow as sf

    p = meta.get(aweme_id)
    if not p:
        print(f"{aweme_id}  不在采集清单 {META} 中")
        return False

    hours = (p.get("duration_seconds") or 0) / 3600
    print("=" * 78)
    print(f"{aweme_id}  {hours:.2f}h  {(p.get('author') or '')[:12]}  "
          f"{(p.get('description') or '')[:40]}")
    url = (p.get("play_url") or "").strip()
    if not url:
        print("  无 play_url（需先跑 collect_images.py 采集）")
        return False
    br = url.split("br=")[1].split("&")[0] if "br=" in url else "?"
    est_gb = (p.get("duration_seconds") or 0) * int(br) / 8 / 1024 / 1024 if br.isdigit() else 0
    print(f"  br={br}  整条视频流预估 {est_gb:.2f} GB（音频只占约 {est_gb/28:.2f} GB）")

    exe = sf._ffmpeg_exe()
    if not exe:
        print("  ** 找不到 ffmpeg（PATH 与 imageio-ffmpeg 都没有）")
        return False
    print(f"  ffmpeg = {Path(exe).name}")

    rate, bitrate = sf._audio_encode_settings()
    headers = ("Referer: https://www.douyin.com/\r\n"
               f"User-Agent: {sf.FFMPEG_UA}\r\n")

    with tempfile.TemporaryDirectory(prefix="douyin-seg-verify-") as td:
        root = Path(td)
        t0 = time.time()
        try:
            cp = subprocess.run(
                [exe, "-nostdin", "-y", "-hide_banner", "-loglevel", "warning",
                 "-headers", headers,
                 "-reconnect", "1", "-reconnect_streamed", "1",
                 "-reconnect_delay_max", "10",
                 "-i", url, "-t", str(probe_seconds),
                 "-vn", "-ac", "1", "-ar", rate, "-b:a", bitrate,
                 "-f", "segment", "-segment_time", str(seg_seconds),
                 "-reset_timestamps", "1",
                 str(root / "part-%03d.mp3")],
                capture_output=True, text=True, timeout=900, check=False)
        except subprocess.TimeoutExpired:
            print(f"  ** 拉流超时（>{probe_seconds}s 未完成）")
            return False
        elapsed = time.time() - t0
        parts = sorted(x for x in root.glob("part-*.mp3") if x.stat().st_size > 0)
        print(f"  拉流+切段：返回码={cp.returncode} 耗时={elapsed:.1f}s 切出 {len(parts)} 段"
              f"  （实测吞吐 ≈ {probe_seconds * (int(br) if br.isdigit() else 0) / 8 / 1024 / max(elapsed,0.1):.2f} MB/s）")
        if cp.stderr.strip():
            print("  ffmpeg 提示:", cp.stderr.strip().splitlines()[-2:])

        if not parts:
            return False

        key = os.environ.get("SILICONFLOW_API_KEY", "").strip()
        if not key:
            print("  切段 OK，但缺 SILICONFLOW_API_KEY，跳过上传验证")
            return True
        try:
            text = sf._upload_transcribe(parts[0], key, sf.DEFAULT_MODEL, sf.DEFAULT_ENDPOINT)
        except Exception as exc:  # noqa: BLE001
            print(f"  ** 首段转录失败：{type(exc).__name__}: {exc}")
            return False
        if not text:
            print("  ** 首段转录返回空")
            return False
        print(f"  首段转录 OK：{len(text)} 字  「{text[:70]}」")
        return True


def main() -> None:
    ap = argparse.ArgumentParser(description="长视频切段转录快速验证")
    ap.add_argument("aweme_ids", nargs="*", default=None)
    ap.add_argument("--probe", type=int, default=180, help="拉流时长（秒），默认 180")
    ap.add_argument("--seg", type=int, default=60, help="试切段长（秒），默认 60")
    args = ap.parse_args()

    if not META.exists():
        raise SystemExit(f"未找到采集清单 {META}，先跑 collect_images.py")
    meta = {str(x["aweme_id"]): x for x in json.loads(META.read_text(encoding="utf-8"))}

    targets = args.aweme_ids or DEFAULT_TARGETS
    results = [probe(a, meta, args.probe, args.seg) for a in targets]

    print("\n" + "=" * 78)
    print(f"验证结果：{sum(results)}/{len(results)} 通过")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    # 采集/转录都直连，清掉 harness 注入的代理变量
    for var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        os.environ.pop(var, None)
    main()
