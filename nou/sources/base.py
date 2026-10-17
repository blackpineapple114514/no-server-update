# -*- coding: utf-8 -*-
"""源接口 + 一个够用的 HTTP 小工具（gzip/deflate、UA、超时）。

每个源只做一件事：`fetch()` 返回 `Release(version, url, notes)`，失败抛异常。
不要把重试、缓存、回落写在源里——那是 Checker 的事。
"""
from __future__ import annotations

import gzip
import urllib.error
import urllib.parse
import urllib.request
import zlib

__all__ = ["Source", "http_get", "http_post"]

UA_TMPL = "no-server-update/0.1 (+%s)"


class Source:
    """源的基类。子类只需实现 fetch()。"""

    name = "source"
    authoritative = True        # 主源：它的失败不该被兜底源洗白

    def fetch(self, timeout: float = 8.0):        # pragma: no cover - 抽象
        raise NotImplementedError


def _decompress(raw: bytes, encoding: str) -> bytes:
    enc = (encoding or "").lower()
    if "gzip" in enc:
        return gzip.decompress(raw)
    if "deflate" in enc:
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw


def _request(url: str, data: bytes = None, timeout: float = 8.0,
             referer: str = "", ua_suffix: str = "anonymous") -> str:
    req = urllib.request.Request(url, data=data)
    req.add_header("User-Agent", UA_TMPL % ua_suffix)
    req.add_header("Accept", "*/*")
    req.add_header("Accept-Encoding", "gzip, deflate")
    if referer:
        req.add_header("Referer", referer)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return _decompress(raw, r.headers.get("Content-Encoding")).decode(
                "utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise RuntimeError("HTTP %s %s" % (e.code, url)) from e
    except urllib.error.URLError as e:
        raise RuntimeError("连不上 %s（%s）" % (urllib.parse.urlsplit(url).netloc, e.reason)) from e


def http_get(url: str, timeout: float = 8.0, referer: str = "",
             ua_suffix: str = "anonymous") -> str:
    return _request(url, None, timeout, referer, ua_suffix)


def http_post(url: str, fields: dict, timeout: float = 8.0, referer: str = "",
              ua_suffix: str = "anonymous") -> str:
    body = urllib.parse.urlencode(fields).encode()
    return _request(url, body, timeout, referer, ua_suffix)
