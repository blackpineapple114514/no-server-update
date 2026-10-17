# -*- coding: utf-8 -*-
"""通用的「检查更新」实现：只读探测、多源回落、失败不伪装成最新。

设计约定见 README「三条铁律」；细节见 docs/设计.md。

    from nou import Checker
    from nou.sources import LanzouFolder

    ck = Checker(current="1.2.0", sources=[LanzouFolder(url, password="abcd")])
    r = ck.check()
    if r.ok and r.has_update:
        open_browser(r.url)
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Iterable, List, Optional

from .version import is_newer, max_version

__all__ = ["Release", "Result", "Checker"]

CACHE_TTL = 30 * 60          # 30 分钟：检查更新不是实时业务，对源站礼貌


@dataclass
class Release:
    """一次成功的探测结果。version 是唯一必填项。"""
    version: str
    url: str = ""
    notes: str = ""


@dataclass
class Result:
    """给前端的最终结论。`ok` 的含义是「确实问到了版本」，不是「请求没报错」。"""
    ok: bool
    current: str
    latest: str = ""
    has_update: bool = False
    url: str = ""
    notes: str = ""
    source: str = ""
    error: str = ""
    stale: bool = False                 # 用的是上次成功结果（可能已过期）

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _Cache:
    ts: float = 0.0
    good: Optional[dict] = None         # 上次成功的 Result（含 ok=True 的快照）
    last: Optional[dict] = None         # 上次返回值（含失败）

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class Checker:
    """按顺序试多个源；第一个能给出版本的作为权威，其余只做兜底。"""

    def __init__(self, current: str, sources: Iterable, ttl: int = CACHE_TTL,
                 state_path: str = "", timeout: float = 8.0):
        self.current = str(current)
        self.sources = list(sources)
        self.ttl = int(ttl)
        self.timeout = timeout
        self.state_path = state_path or ""
        self._cache = _Cache()
        self._load_state()

    # ---------------------------------------------------------------- 缓存
    def _load_state(self) -> None:
        if not self.state_path or not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                d = json.load(f)
            self._cache = _Cache(ts=float(d.get("ts") or 0),
                                 good=d.get("good"), last=d.get("last"))
        except Exception:                                   # noqa: BLE001
            self._cache = _Cache()

    def _save_state(self) -> None:
        if not self.state_path:
            return
        try:
            d = os.path.dirname(os.path.abspath(self.state_path))
            if d:
                os.makedirs(d, exist_ok=True)
            tmp = self.state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(self._cache.to_json())
            os.replace(tmp, self.state_path)
        except Exception:                                   # noqa: BLE001
            pass                                            # 缓存写不进去不影响主流程

    # ---------------------------------------------------------------- 主流程
    def check(self, force: bool = False) -> Result:
        now = time.time()
        if not force and self._cache.last and (now - self._cache.ts) < self.ttl:
            return Result(**self._cache.last)

        releases: List[tuple] = []          # (source_name, Release)
        errors: List[tuple] = []           # (source_name, message)
        for src in self.sources:
            try:
                rel = src.fetch(timeout=self.timeout)
                if rel and str(rel.version or "").strip():
                    releases.append((getattr(src, "name", "?"), rel))
            except Exception as e:                          # noqa: BLE001
                errors.append((getattr(src, "name", "?"), str(e)[:120]))

        out = Result(ok=False, current=self.current,
                     error="；".join("%s：%s" % (n, m) for n, m in errors)[:400])

        if releases:
            latest = max_version([r.version for _, r in releases])
            winner = next(r for _, r in releases if r.version == latest)
            out.ok = True
            out.latest = latest
            out.url = winner.url
            out.notes = winner.notes
            out.source = next(n for n, r in releases if r is winner)
            out.has_update = is_newer(latest, self.current)

            # 主源失败、兜底源又只说「不比我新」→ 判定为「未知」，不能算最新。
            failed = {n for n, _ in errors}
            primary_failed = bool(self.sources) and \
                getattr(self.sources[0], "name", "?") in failed
            if primary_failed and not out.has_update:
                out.ok = False
                out.error = ("主源不可用，兜底源的版本不比当前新（%s）" % out.error)[:400]
        else:
            # 全部失败：如果上次成功结果说「有新版」，仍然提示，但标记为可能过期。
            good = self._cache.good
            if good and good.get("has_update"):
                out = Result(**good)
                out.ok = False
                out.stale = True
                out.error = "本次检查失败，沿用上次结果（可能已过期）：%s" % out.error

        snap = out.to_dict()
        self._cache.ts = now
        self._cache.last = snap
        if out.ok:
            self._cache.good = snap
        self._save_state()
        return out
