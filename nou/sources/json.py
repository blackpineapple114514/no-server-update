# -*- coding: utf-8 -*-
"""任意静态 JSON 当版本清单——最没有副作用的一种源。

服务端放一个文件（对象存储、Pages、甚至网盘直链都行）：

    {"version": "1.3.0",
     "url": "https://example.com/app-1.3.0.exe",
     "notes": "修了 XXX"}

程序只 GET 它。没有账号、没有令牌、没有反爬——**能选这个就别选网盘**。
"""
from __future__ import annotations

import json

from .base import Source, http_get

__all__ = ["StaticJson"]

_VERSION_KEYS = ("version", "latest", "latest_version", "tag", "tag_name")
_URL_KEYS = ("url", "download", "download_url", "href")
_NOTES_KEYS = ("notes", "changelog", "body", "message")


def _first(d: dict, keys) -> str:
    for k in keys:
        v = d.get(k)
        if isinstance(v, (str, int, float)) and str(v).strip():
            return str(v).strip()
    return ""


class StaticJson(Source):
    """GET 一个 JSON，取 version / url / notes。字段名可用 aliases 覆盖。"""

    name = "static-json"

    def __init__(self, url: str, version_keys=_VERSION_KEYS, url_keys=_URL_KEYS,
                 notes_keys=_NOTES_KEYS, ua_suffix: str = "update-check"):
        self.url = url
        self.version_keys = tuple(version_keys)
        self.url_keys = tuple(url_keys)
        self.notes_keys = tuple(notes_keys)
        self.ua_suffix = ua_suffix

    def fetch(self, timeout: float = 8.0):
        from ..checker import Release

        txt = http_get(self.url, timeout=timeout, ua_suffix=self.ua_suffix)
        try:
            d = json.loads(txt)
        except Exception as e:                            # noqa: BLE001
            raise RuntimeError("不是合法 JSON（%s）" % str(e)[:60]) from e
        if not isinstance(d, dict):
            raise RuntimeError("JSON 顶层得是对象")
        ver = _first(d, self.version_keys).lstrip("vV")
        if not ver:
            raise RuntimeError("JSON 里没有版本字段（试过 %s）" % ", ".join(self.version_keys))
        return Release(version=ver,
                       url=_first(d, self.url_keys),
                       notes=_first(d, self.notes_keys)[:500])
