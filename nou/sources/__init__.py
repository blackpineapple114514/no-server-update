# -*- coding: utf-8 -*-
"""可插拔的更新源。

统一契约：`fetch(timeout=…) -> Release(version, url, notes)`，失败抛异常。
"""
from .base import Source
from .github import GithubReleases
from .json import StaticJson
from .lanzou import LanzouFile, LanzouFolder

__all__ = ["Source", "StaticJson", "GithubReleases", "LanzouFolder", "LanzouFile"]
