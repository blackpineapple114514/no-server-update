# -*- coding: utf-8 -*-
"""GitHub Releases 当源。

对海外用户最省事；国内直连经常超时，所以通常只当**兜底**，或者给完全面向海外的
项目当主源。未认证请求每小时 60 次，认证后 5000 次——检查更新是完全够的。
"""
from __future__ import annotations

import json
import os

from .base import Source, http_get

__all__ = ["GithubReleases"]


class GithubReleases(Source):
    """GET /repos/{owner}/{repo}/releases/latest → tag_name。"""

    name = "github"

    def __init__(self, repo: str, token: str = "", ua_suffix: str = "update-check"):
        self.repo = repo.strip("/")
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        self.ua_suffix = ua_suffix

    def fetch(self, timeout: float = 8.0):
        from ..checker import Release

        url = "https://api.github.com/repos/%s/releases/latest" % self.repo
        # 直接复用 http_get 会带 Accept-Encoding，GitHub 也接受；token 用查询头传
        txt = _get_with_headers(url, timeout, self.ua_suffix,
                                {"Authorization": "Bearer " + self.token} if self.token else {})
        try:
            d = json.loads(txt)
        except Exception as e:                            # noqa: BLE001
            raise RuntimeError("不是合法 JSON（%s）" % str(e)[:60]) from e
        tag = str(d.get("tag_name") or "").strip().lstrip("vV")
        if not tag:
            raise RuntimeError("仓库没有 release（或返回里没有 tag_name）")
        return Release(version=tag,
                       url=str(d.get("html_url") or ""),
                       notes=str(d.get("body") or "")[:500])


def _get_with_headers(url: str, timeout: float, ua_suffix: str, headers: dict) -> str:
    """http_get 的薄封装：这个源需要额外的 Authorization 头。"""
    import urllib.request
    from .base import UA_TMPL, _decompress

    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA_TMPL % ua_suffix)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Accept-Encoding", "gzip, deflate")
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return _decompress(r.read(), r.headers.get("Content-Encoding")).decode(
            "utf-8", "replace")
