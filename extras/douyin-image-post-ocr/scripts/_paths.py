"""统一路径解析 —— 本技能所有脚本共用。

解析优先级：**环境变量 > 自动探测的默认布局**。
换机器 / 换目录时不用改脚本，导出对应环境变量即可。

| 环境变量 | 含义 | 默认值 |
|---|---|---|
| `DOUYIN_OCR_ROOT` | 工作根目录 | 自动探测 `~/OneDrive/douyin`，退回 `~/douyin` |
| `DOUYIN_UPSTREAM` | 上游项目目录 | `$DOUYIN_OCR_ROOT/douyin-favorites-to-knowledge` |
| `DOUYIN_SITE_PACKAGES` | 打过补丁的 site-packages | `$DOUYIN_UPSTREAM/.venv/**/site-packages` |
| `DOUYIN_OCR_WORK` | 中间产物目录 | `$DOUYIN_OCR_ROOT/ocr_test` |
| `DOUYIN_OCR_KB` | Obsidian 知识库目录 | `~/OneDrive/Apps/Obsidian library/抖音知识库` |
| `DOUYIN_OCR_LEDGER` | 账本 sqlite3 文件 | `%APPDATA%/douyin-favorites-to-knowledge/state/ledger.sqlite3` |
"""
from __future__ import annotations

import os
from pathlib import Path

HOME = Path.home()


def _first_existing(*candidates: Path) -> Path:
    """返回第一个存在的候选路径；都不存在时返回第一个（便于报错时定位）。"""
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


# 工作根目录
ROOT = Path(
    os.environ.get("DOUYIN_OCR_ROOT")
    or _first_existing(HOME / "OneDrive" / "douyin", HOME / "douyin")
)

# 上游项目
UPSTREAM = Path(
    os.environ.get("DOUYIN_UPSTREAM") or (ROOT / "douyin-favorites-to-knowledge")
)


def _guess_site_packages() -> Path:
    """Windows venv 是 .venv/Lib/site-packages，POSIX 是 .venv/lib/pythonX.Y/site-packages。"""
    venv = UPSTREAM / ".venv"
    win = venv / "Lib" / "site-packages"
    if win.exists():
        return win
    lib = venv / "lib"
    if lib.exists():
        for p in sorted(lib.glob("python*/site-packages")):
            return p
    return win


SITE_PACKAGES = Path(
    os.environ.get("DOUYIN_SITE_PACKAGES") or _guess_site_packages()
)

# 中间产物目录
WORK = Path(os.environ.get("DOUYIN_OCR_WORK") or (ROOT / "ocr_test"))

# Obsidian 知识库
KB = Path(
    os.environ.get("DOUYIN_OCR_KB")
    or (HOME / "OneDrive" / "Apps" / "Obsidian library" / "抖音知识库")
)

# 账本
_APPDATA = Path(os.environ.get("APPDATA") or (HOME / "AppData" / "Roaming"))
LEDGER = Path(
    os.environ.get("DOUYIN_OCR_LEDGER")
    or (_APPDATA / "douyin-favorites-to-knowledge" / "state" / "ledger.sqlite3")
)


def ensure_site_packages_on_path() -> None:
    """把打过补丁的 site-packages 插到 sys.path 最前，供脚本 import 上游包。"""
    import sys

    p = str(SITE_PACKAGES)
    if p not in sys.path:
        sys.path.insert(0, p)


if __name__ == "__main__":  # 自检：打印解析结果，方便排查路径问题
    for name in ("ROOT", "UPSTREAM", "SITE_PACKAGES", "WORK", "KB", "LEDGER"):
        p = globals()[name]
        print(f"{name:15s} {'OK ' if p.exists() else 'MISS'} {p}")
