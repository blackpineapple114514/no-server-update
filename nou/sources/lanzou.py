# -*- coding: utf-8 -*-
"""网盘目录当版本清单（以蓝奏云为例，结构对同类网盘可照搬）。

为什么用「目录」而不是「单个文件分享」：
    单文件分享的文件 id 每传一版就变，想让链接固定只能靠改名（多数网盘要付费）；
    目录分享的链接锚在目录上，增删文件都不影响。

一次 fetch 是两跳：
    ① GET 分享页 → 拿 fid / uid / puid 和两个一次性令牌 t / k
    ② POST /filemoreajax.php → {"zt":1,"text":[{name_all,size,time,id}, ...]}

两个必须知道的细节：
    * 令牌的**变量名是随机的**（同一站点不同分享页都不一样）⇒ 只能按字段名取，
      再把标识符按 `var X = '...'` 解引用。
    * `zt=2` 是「目录是空的」，不是错误；`zt=3` 才是提取码不对。
"""
from __future__ import annotations

import json
import re
import urllib.parse

from .base import Source, http_get, http_post

__all__ = ["LanzouFolder", "LanzouFile", "parse_folder_form", "parse_file_list",
           "pick_latest"]

VER_RE = re.compile(r"(\d+\.\d+(?:\.\d+)*)")


def derive_dl_host(share_url: str) -> str:
    """从分享链接推下载页域名。

    分享页与下载页的域名后缀经常不同（同一子域、不同二级域名）：实测
    `*.lanzoup.com` 的文件页是残页，`*.lanzoue.com` 才是完整的。所以默认把
    已知的「分享用后缀」换成「下载用后缀」，其余情况原样返回。
    """
    host = urllib.parse.urlsplit(share_url).netloc.lower()
    for a, b in (("lanzoup.com", "lanzoue.com"),
                 ("lanzoux.com", "lanzoue.com"),
                 ("lanzoui.com", "lanzoue.com")):
        if host == a:
            return b
        if host.endswith("." + a):
            return host[:-len(a)] + b
    return host


def parse_folder_form(html: str) -> dict:
    """从分享页里把列表接口需要的字段取出来（含令牌解引用）。"""
    m = re.search(r"filemoreajax\.php\?file=(\d+)", html or "")
    if not m:
        raise RuntimeError("分享页结构变了：找不到列表接口（fid）")
    fid = m.group(1)
    # 表单就在列表接口附近；按字段名取，不依赖变量名
    blk = html[max(0, m.start() - 1500): m.start() + 1500]

    def field(key: str) -> str:
        # 键名带不带引号都可能；值可能是字符串/数字，也可能是一个变量名
        mm = re.search(
            r"(?<![A-Za-z0-9_])[\"']?%s[\"']?\s*:\s*(?:'([^']*)'|\"([^\"]*)\"|(\d+)|([A-Za-z_]\w*))"
            % key, blk)
        if not mm:
            return ""
        for g in mm.groups()[:3]:
            if g is not None:
                return g
        ident = mm.group(4)
        if not ident or ident in ("true", "false", "null", "undefined"):
            return ""
        v = re.search(r"var\s+%s\s*=\s*['\"]([^'\"]*)['\"]" % re.escape(ident), html)
        if not v:
            v = re.search(r"var\s+%s\s*=\s*(\d+)" % re.escape(ident), html)
        return v.group(1) if v else ""

    return {"fid": fid, "uid": field("uid"), "puid": field("puid"),
            "t": field("t"), "k": field("k")}


def parse_file_list(payload: str) -> list:
    """把列表接口的 JSON 归一成 [{name,id,size,time}]；空目录返回 []。"""
    try:
        d = json.loads(payload)
    except Exception as e:                                # noqa: BLE001
        raise RuntimeError("列表返回的不是 JSON：%s" % (payload or "")[:80]) from e
    zt = str(d.get("zt"))
    if zt == "2":                                         # 空目录：正常状态
        return []
    if zt == "3":
        raise RuntimeError("提取码不对（%s）" % str(d.get("info") or "")[:40])
    if zt != "1":
        raise RuntimeError("接口回 zt=%s %s" % (zt, str(d.get("info") or "")[:40]))
    out = []
    for row in (d.get("text") or []):
        if not isinstance(row, dict):
            continue
        if str(row.get("id") or "") in ("", "-1"):        # -1 = 推广位
            continue
        out.append({"name": str(row.get("name_all") or ""),
                    "id": str(row.get("id") or ""),
                    "size": str(row.get("size") or ""),
                    "time": str(row.get("time") or "")})
    return out


def pick_latest(rows: list):
    """按版本号数值挑最大的一行；没有带版本号的文件返回 None。"""
    from ..version import parse

    best = None
    for r in rows:
        m = VER_RE.search(r.get("name") or "")
        if not m:
            continue
        if best is None or parse(m.group(1)) > parse(best[0]):
            best = (m.group(1), r)
    return best


class LanzouFolder(Source):
    """网盘目录。

    share_url   : 目录分享链接（固定不变）
    password    : 提取码；没有就传空
    dl_host     : 拼下载页用的域名；缺省从分享链接推导（见 derive_dl_host）
    """

    name = "lanzou-folder"

    def __init__(self, share_url: str, password: str = "",
                 dl_host: str = "", ua_suffix: str = "update-check"):
        self.share_url = share_url
        self.password = password or ""
        self.dl_host = dl_host or derive_dl_host(share_url)
        self.ua_suffix = ua_suffix

    def fetch(self, timeout: float = 8.0):
        from ..checker import Release

        host = urllib.parse.urlsplit(self.share_url).netloc
        html = http_get(self.share_url, timeout=timeout, referer=self.share_url,
                        ua_suffix=self.ua_suffix)
        form = parse_folder_form(html)
        if not form["t"] or not form["k"]:
            raise RuntimeError("分享页结构变了：拿不到列表令牌")
        body = {
            "lx": "2", "fid": form["fid"], "uid": form["uid"], "puid": form["puid"],
            "pg": "1", "rep": "0", "t": form["t"], "k": form["k"], "up": "1",
            "ls": "1", "pwd": self.password,
        }
        payload = http_post("https://%s/filemoreajax.php?file=%s" % (host, form["fid"]),
                            body, timeout=timeout, referer=self.share_url,
                            ua_suffix=self.ua_suffix)
        rows = parse_file_list(payload)
        best = pick_latest(rows)
        if not best:
            raise RuntimeError("目录里没有形如 xxx__v1.2.3.exe 的文件（共 %d 个）" % len(rows))
        ver, row = best
        return Release(version=ver,
                       url="https://%s/%s" % (self.dl_host, row["id"]),
                       notes="%s · %s" % (row["name"], row["size"]))


class LanzouFile(Source):
    """单个文件分享：只能靠重命名来换版本（多数网盘改名要付费）。

    页面标题就是文件名；《div id="filenajax"》里也是。带提取码的分享页拿不到
    文件名（标题为空），所以这个源只适合**无提取码**的分享。
    """

    name = "lanzou-file"

    def __init__(self, share_url: str, ua_suffix: str = "update-check"):
        self.share_url = share_url
        self.ua_suffix = ua_suffix

    def fetch(self, timeout: float = 8.0):
        from ..checker import Release

        html = http_get(self.share_url, timeout=timeout, referer=self.share_url,
                        ua_suffix=self.ua_suffix)
        m = re.search(r"<title>\s*(.*?)\s*</title>", html, re.S) or \
            re.search(r'id="filenajax"[^>]*>\s*([^<]+)', html)
        name = (m.group(1).strip() if m else "")
        if not name or _looks_like_landing_page(name):
            raise RuntimeError("分享页拿不到文件名（多半是带提取码，或页面改版了）")
        vm = VER_RE.search(name)
        if not vm:
            raise RuntimeError("文件名里没有版本号：%s" % name[:60])
        return Release(version=vm.group(1), url=self.share_url, notes=name)


def _looks_like_landing_page(title: str) -> bool:
    t = title.lower()
    return ("lanzou" in t or "蓝奏" in title or "密码" in title or len(t) < 4)
