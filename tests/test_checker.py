# -*- coding: utf-8 -*-
"""多源检查的判定表 + 缓存语义。用假源，不联网。"""
import json
import os
import tempfile
import time
import unittest

from nou.checker import Checker, Release
from nou.sources.base import Source


class Fake(Source):
    """可编排的假源：返回值 / 抛异常 / 记调用次数。"""

    def __init__(self, name, version="", url="", error=""):
        self.name = name
        self._version = version
        self._url = url
        self._error = error
        self.calls = 0

    def fetch(self, timeout=8.0):
        self.calls += 1
        if self._error:
            raise RuntimeError(self._error)
        return Release(version=self._version, url=self._url, notes="")


def ok(name, ver):
    return Fake(name, version=ver, url="https://example.com/" + ver)


def bad(name, msg="连不上"):
    return Fake(name, error=msg)


class TestDecisionTable(unittest.TestCase):
    def test_primary_ok_no_update(self):
        r = Checker("1.2.0", [ok("a", "1.2.0")]).check()
        self.assertTrue(r.ok)
        self.assertFalse(r.has_update)

    def test_primary_ok_has_update(self):
        r = Checker("1.2.0", [ok("a", "1.3.0")]).check()
        self.assertTrue(r.ok)
        self.assertTrue(r.has_update)
        self.assertEqual(r.latest, "1.3.0")
        self.assertEqual(r.url, "https://example.com/1.3.0")

    def test_primary_failed_fallback_newer_is_trusted(self):
        r = Checker("1.2.0", [bad("a"), ok("b", "1.3.0")]).check()
        self.assertTrue(r.ok)
        self.assertTrue(r.has_update)

    def test_primary_failed_fallback_not_newer_is_unknown(self):
        # 核心用例：兜底源只说「不比我新」，不能宣布「已是最新」
        r = Checker("1.3.0", [bad("a"), ok("b", "1.0.0")]).check()
        self.assertFalse(r.ok)
        self.assertIn("主源", r.error)

    def test_all_failed(self):
        r = Checker("1.2.0", [bad("a"), bad("b", "超时")]).check()
        self.assertFalse(r.ok)
        self.assertIn("连不上", r.error)
        self.assertIn("超时", r.error)

    def test_fallback_not_counted_when_primary_ok(self):
        a, b = ok("a", "1.2.0"), bad("b")
        r = Checker("1.2.0", [a, b]).check()
        self.assertTrue(r.ok)      # 主源已有答案，备用失败无关
        self.assertFalse(r.has_update)

    def test_empty_version_treated_as_failure(self):
        r = Checker("1.2.0", [Fake("a", version="")]).check()
        self.assertFalse(r.ok)

    def test_source_name_reported(self):
        r = Checker("1.0.0", [bad("a"), ok("b", "2.0.0")]).check()
        self.assertEqual(r.source, "b")


class TestCache(unittest.TestCase):
    def test_second_call_hits_cache(self):
        a = ok("a", "1.3.0")
        ck = Checker("1.2.0", [a], ttl=1800)
        ck.check()
        ck.check()
        self.assertEqual(a.calls, 1)

    def test_force_bypasses_cache(self):
        a = ok("a", "1.3.0")
        ck = Checker("1.2.0", [a], ttl=1800)
        ck.check()
        ck.check(force=True)
        self.assertEqual(a.calls, 2)

    def test_ttl_expiry(self):
        a = ok("a", "1.3.0")
        ck = Checker("1.2.0", [a], ttl=0)
        ck.check()
        time.sleep(0.01)
        ck.check()
        self.assertEqual(a.calls, 2)

    def test_failure_keeps_last_good(self):
        # 先成功（有新版），再全挂：应沿用上次结论并标 stale
        a = ok("a", "1.3.0")
        ck = Checker("1.2.0", [a], ttl=0)
        ck.check()
        a._error = "断网"
        r = ck.check()
        self.assertFalse(r.ok)
        self.assertTrue(r.stale)
        self.assertTrue(r.has_update)      # 仍然提示，但明确标为可能过期

    def test_failure_does_not_invent_update(self):
        a = ok("a", "1.2.0")
        ck = Checker("1.2.0", [a], ttl=0)
        r1 = ck.check()
        self.assertTrue(r1.ok)
        a._error = "断网"
        r2 = ck.check()
        self.assertFalse(r2.ok)
        self.assertFalse(r2.has_update)


class TestPersistedState(unittest.TestCase):
    def test_state_roundtrip(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "state.json")
        a = ok("a", "1.3.0")
        Checker("1.2.0", [a], ttl=1800, state_path=p).check()
        self.assertTrue(os.path.exists(p))
        with open(p, encoding="utf-8") as f:
            json.load(f)                      # 必须是合法 JSON

        b = ok("a", "9.9.9")                  # 新实例应命中磁盘缓存，不调用源
        r = Checker("1.2.0", [b], ttl=1800, state_path=p).check()
        self.assertEqual(b.calls, 0)
        self.assertEqual(r.latest, "1.3.0")

    def test_broken_state_file_ignored(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "state.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write("{ 这不是 json")
        r = Checker("1.2.0", [ok("a", "1.3.0")], state_path=p).check()
        self.assertTrue(r.ok)                 # 坏缓存不该让检查失败


if __name__ == "__main__":
    unittest.main()
