# -*- coding: utf-8 -*-
"""版本号解析与比较。

只认数字段：`1.10.0 > 1.9.0`（按字符串比会反过来），`v` 前缀可有可无，
缺位补 0，`1.2.3-beta.1` 只取 `1.2.3`。
"""
from __future__ import annotations

import re
from typing import Tuple

__all__ = ["parse", "is_newer", "max_version"]


def parse(v: str) -> Tuple[int, int, int]:
    """把版本串拆成 (major, minor, patch)。取不到数字的段按 0 算。"""
    s = str(v or "").strip().lstrip("vV")
    core = re.split(r"[-+]", s)[0]              # 丢掉预发布/构建元数据
    parts = []
    for seg in core.split("."):
        digits = re.sub(r"\D", "", seg)
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])                     # type: ignore[return-value]


def is_newer(latest: str, current: str) -> bool:
    """latest 是否比 current 新。任一方解析不出数字时，按不更新处理。"""
    if not str(latest or "").strip() or not str(current or "").strip():
        return False
    return parse(latest) > parse(current)


def max_version(versions) -> str:
    """在一组版本串里取最大的那个（返回原串，不是解析结果）。"""
    best = ""
    for v in versions:
        if not str(v or "").strip():
            continue
        if not best or parse(v) > parse(best):
            best = str(v)
    return best
