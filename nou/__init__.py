# -*- coding: utf-8 -*-
"""不依赖服务器的更新检查（no-server update）。

思路：把「版本清单」放在一个地址固定、可匿名读、国内可达的静态位置，程序只读不写。
代码：多源适配（静态 JSON / Releases / 网盘目录）+ 缓存 + 失败语义 + 前端提示。

    from nou import Checker
    from nou.sources import StaticJson, LanzouFolder

    ck = Checker(current="1.2.0", sources=[
        LanzouFolder("https://example.lanzou?.com/bXXXXXXXX", password="abcd"),
        StaticJson("https://example.com/latest.json"),
    ])
    r = ck.check()
    if r.ok and r.has_update:
        print("有新版本", r.latest, r.url)
"""
from .apply import (HELPER_FLAG, UpdateError, apply_update, cleanup_old,
                    download_to, handle_helper_argv, sha256_file, stage_download)
from .checker import CACHE_TTL, Checker, Release, Result
from .finder import default_download_dirs, find_download
from .version import is_newer, max_version, parse

__version__ = "0.1.0"
__all__ = ["Checker", "Release", "Result", "CACHE_TTL",
           "parse", "is_newer", "max_version",
           "apply_update", "handle_helper_argv", "cleanup_old",
           "download_to", "stage_download", "sha256_file",
           "find_download", "default_download_dirs",
           "UpdateError", "HELPER_FLAG"]
