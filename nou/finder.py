# -*- coding: utf-8 -*-
"""在用户机器上「找那个刚下好的新版本」。

为什么需要它：有些网盘（比如蓝奏云）的直链已经挂了人机验证，程序**没法**自己下载——
但用户用浏览器点一下「下载」是可以的。于是把流程切成两段：

    浏览器负责「拿到文件」，本模块负责「认出它是哪一个、有没有被换过」

认人要紧：只按扩展名找会把用户下载的别的东西当成新版本。所以要同时过三关：
文件名里的版本号、大小下限、以及（最好有）文件名里的 sha256 前缀。
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from typing import Iterable, Optional

__all__ = ["find_download", "default_download_dirs"]

CHUNK = 1 << 20


def default_download_dirs() -> list:
    """用户可能把文件放哪儿。只返回**存在**的目录。"""
    home = os.path.expanduser("~")
    cands = [
        os.path.join(home, "Downloads"),
        os.path.join(home, "下载"),
        os.path.join(home, "Desktop"),
        os.path.join(home, "桌面"),
    ]
    out = []
    seen = set()
    for d in cands:
        d = os.path.abspath(d)
        if os.path.isdir(d) and d.lower() not in seen:
            seen.add(d.lower())
            out.append(d)
    return out


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(CHUNK), b""):
            h.update(b)
    return h.hexdigest()


def _version_in(name: str, version: str) -> bool:
    """版本号必须整段匹配：找 1.2.0 时不能命中 1.2.01 或 11.2.0。"""
    pat = r"(?<![\d.])%s(?![\d])" % re.escape(version)
    return re.search(pat, name) is not None


def find_download(dirs: Optional[Iterable[str]] = None, version: str = "",
                  sha_prefix: str = "", suffixes=(".exe",), name_hint: str = "",
                  min_bytes: int = 1 << 20, min_age: float = 2.0,
                  max_candidates: int = 8) -> dict:
    """在 dirs 里找「刚下载的新版本」。

    返回 {"path","size","sha256","mtime","reason"}；找不到返回 {"path": ""...}。
    `reason` 说明为什么没认出来，方便前端给一句人话。

    参数：
        version       期望版本号（从文件名里认）
        sha_prefix    期望前缀（大小写不敏感）；给了就一定校验
        min_age       文件最后修改距今至少多少秒（避免拿到还 .part 的半截文件）
        min_bytes     小于这个就当没下完
    """
    dirs = list(dirs) if dirs is not None else default_download_dirs()
    best = None
    reason = "没在下载目录里找到匹配的文件"
    sigs = []
    for d in dirs:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            if suffixes and not n.lower().endswith(tuple(x.lower() for x in suffixes)):
                continue
            if name_hint and name_hint.lower() not in n.lower():
                continue
            if version and not _version_in(n, version):
                continue
            p = os.path.join(d, n)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if st.st_size < min_bytes:
                reason = "文件太小，可能没下完：%s" % n
                continue
            if min_age and (time.time() - st.st_mtime) < min_age:
                reason = "文件刚出现，可能还在写：%s" % n
                continue
            sigs.append((st.st_mtime, p, st.st_size))
    sigs.sort(reverse=True)
    if not sigs:
        return {"path": "", "size": 0, "sha256": "", "mtime": 0, "reason": reason}

    for mtime, path, size in sigs[:max_candidates]:
        if sha_prefix:
            got = _sha256(path)
            if not got.lower().startswith(sha_prefix.lower()):
                reason = "找到同名文件但哈希不对：%s" % os.path.basename(path)
                continue
        else:
            got = ""
        best = {"path": path, "size": size, "sha256": got, "mtime": mtime,
                "reason": ""}
        break
    if best is None:
        return {"path": "", "size": 0, "sha256": "", "mtime": 0, "reason": reason}
    return best
