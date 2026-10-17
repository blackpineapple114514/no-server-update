# -*- coding: utf-8 -*-
"""静态 JSON 源。最没有副作用的一种源，也是自测最方便的。"""
import json
import unittest
from unittest import mock

from nou.sources import json as J


def fetch_with(payload, **kw):
    src = J.StaticJson("https://example.com/latest.json", **kw)
    with mock.patch.object(J, "http_get", return_value=payload):
        return src.fetch()


class TestStaticJson(unittest.TestCase):
    def test_canonical_fields(self):
        rel = fetch_with(json.dumps({"version": "1.3.0",
                                     "url": "https://example.com/app.exe",
                                     "notes": "修了闪退"}))
        self.assertEqual(rel.version, "1.3.0")
        self.assertEqual(rel.url, "https://example.com/app.exe")
        self.assertEqual(rel.notes, "修了闪退")

    def test_aliases(self):
        rel = fetch_with(json.dumps({"tag_name": "v2.0.0",
                                     "download": "https://example.com/a.exe"}))
        self.assertEqual(rel.version, "2.0.0")
        self.assertEqual(rel.url, "https://example.com/a.exe")

    def test_version_missing(self):
        with self.assertRaises(RuntimeError) as cm:
            fetch_with(json.dumps({"url": "https://example.com/a.exe"}))
        self.assertIn("版本字段", str(cm.exception))

    def test_not_json(self):
        with self.assertRaises(RuntimeError):
            fetch_with("<!DOCTYPE html>")

    def test_top_level_must_be_object(self):
        with self.assertRaises(RuntimeError):
            fetch_with('["1.0.0"]')

    def test_notes_truncated(self):
        rel = fetch_with(json.dumps({"version": "1.0.0", "notes": "x" * 2000}))
        self.assertLessEqual(len(rel.notes), 500)


if __name__ == "__main__":
    unittest.main()
